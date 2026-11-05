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

use std::path::Path;
use std::time::Duration;

use serde_json::{json, Value};
use sunday_host::provider::{self, ProviderBook, TransportPolicy, Vendor};
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
        "config.models.usage" => Ok(
            json!({ "usage": {}, "total": {}, "range": params.get("range").cloned().unwrap_or(Value::Null) }),
        ),
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
    load_dir(&state.data_dir)
}

fn load_dir(dir: &Path) -> Result<config::CoreConfig, String> {
    config::load_or_default(dir).map_err(|error| error.to_string())
}

fn store(state: &CoreState, config: &config::CoreConfig) -> Result<(), String> {
    store_dir(&state.data_dir, config)
}

fn store_dir(dir: &Path, config: &config::CoreConfig) -> Result<(), String> {
    config::save(dir, config).map_err(|error| error.to_string())
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
    let text = |key: &str| {
        params
            .get(key)
            .and_then(Value::as_str)
            .map(str::trim)
            .unwrap_or("")
    };

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

/// Asks the endpoint what it serves, in the order the binding gate requires.
///
/// **The key never leaves for an address that has not been approved.** An earlier
/// version posted the stored key straight at `base_url`, so editing the address in
/// the settings screen shipped the key to a host nobody had vetted — the exact hole
/// the provider binding exists to close.
///
/// The order is now fixed and each step is visible in the code below:
///
/// 1. `provider::admit` vets the destination **offline**: scheme, host and transport
///    policy. A refused address gets no request at all, so a public plain-http host
///    can never be probed in the first place.
/// 2. A **credential-free** request runs next. It sends no `Authorization` header and
///    therefore cannot spend a secret no matter who receives it.
/// 3. Only when that request proves something answers at this address is
///    `confirm_endpoint` written, and only then may a second request carry the key.
///
/// Approval is thus earned by a reachable address, never asserted by a button, and
/// `write_provider` drops it again the moment the address changes. A front-end
/// that hides a checkbox cannot satisfy this: the rule lives where the socket is
/// opened.
async fn probe(state: &CoreState, params: &Value) -> Result<Value, String> {
    probe_at(&state.data_dir, params).await
}

/// The probe, against a data directory rather than a live host.
///
/// Split out so the no-key-before-approval rule can be checked against a real
/// listening socket in a test, with no Android device involved.
pub async fn probe_at(dir: &Path, params: &Value) -> Result<Value, String> {
    probe_at_timeout(dir, params, PROBE_TIMEOUT).await
}

/// The probe with an explicit timeout, so a test can prove "silence means no
/// approval" without waiting out the production budget.
async fn probe_at_timeout(dir: &Path, _params: &Value, timeout: Duration) -> Result<Value, String> {
    let mut config = load_dir(dir)?;
    let key = crate::secrets::read_api_key(dir).unwrap_or_default();
    let has_key = !key.trim().is_empty();
    let vendor = Vendor::parse(&config.provider).unwrap_or(Vendor::Compatible);
    let transport = TransportPolicy {
        allow_insecure_local: config.allow_insecure_local,
    };

    // Step 1: the gate, offline. Plain http to a public host, an unusable scheme or
    // a malformed address stops here, before a socket is ever opened.
    let approved = match provider::admit(
        vendor,
        &config.base_url,
        has_key,
        transport,
        &ProviderBook::load(&crate::provider::bindings_path(dir)),
    ) {
        Ok(admission) => admission.is_cleared(),
        Err(error) => {
            let checked_at = timestamp();
            return Ok(probe_reply(status_entry(
                "invalid",
                error.to_string(),
                0,
                false,
                0,
                0,
                &checked_at,
            )));
        }
    };

    // Step 2: no credentials. Nothing about the key is involved in deciding whether
    // this address deserves approval.
    let started = std::time::Instant::now();
    let checked_at = timestamp();
    let anonymous = sunday_llm::probe_endpoint(&config.base_url, "", timeout).await;
    let latency = started.elapsed().as_millis() as u64;
    let reached = match anonymous {
        Err(error) => {
            // Nothing answered, so nothing is approved. Silence is not an identity.
            return Ok(probe_reply(status_entry(
                "unreachable",
                redact(&error.to_string(), &key),
                latency,
                false,
                0,
                0,
                &checked_at,
            )));
        }
        Ok(outcome) => outcome,
    };

    if !approved {
        config.confirm_endpoint = true;
        store_dir(dir, &config)?;
    }

    if !has_key {
        return Ok(probe_reply(from_outcome(
            &reached,
            latency,
            false,
            &checked_at,
        )));
    }

    // Step 3: the key may travel now, and only to the address just proven reachable.
    let started = std::time::Instant::now();
    let authenticated = sunday_llm::probe_endpoint(&config.base_url, &key, timeout).await;
    let latency = started.elapsed().as_millis() as u64;
    let status = match authenticated {
        Ok(outcome) => from_outcome(&outcome, latency, true, &checked_at),
        Err(error) => status_entry(
            "unreachable",
            redact(&error.to_string(), &key),
            latency,
            true,
            0,
            0,
            &checked_at,
        ),
    };
    Ok(probe_reply(status))
}

/// One status row. `used_api_key` is reported so the screen can say which kind of
/// probe produced the answer; it is a boolean, never the key.
fn status_entry(
    state: &str,
    detail: impl Into<String>,
    latency: u64,
    used_api_key: bool,
    http_status: u16,
    model_count: usize,
    checked_at: &str,
) -> Value {
    json!({
        "state": state,
        "detail": detail.into(),
        "latency_ms": latency,
        "http_status": http_status,
        "model_count": model_count,
        "checked_at": checked_at,
        "used_api_key": used_api_key,
    })
}

fn from_outcome(
    outcome: &sunday_llm::ProbeOutcome,
    latency: u64,
    used_api_key: bool,
    checked_at: &str,
) -> Value {
    match outcome {
        sunday_llm::ProbeOutcome::Models(names) => status_entry(
            "ok",
            if names.is_empty() {
                "端点可达，但没有返回任何模型".to_owned()
            } else {
                format!("{} 个模型可用：{}", names.len(), names.join(", "))
            },
            latency,
            used_api_key,
            200,
            names.len(),
            checked_at,
        ),
        sunday_llm::ProbeOutcome::Unauthorized => status_entry(
            "unauthorized",
            "端点可达，但拒绝了这组凭据",
            latency,
            used_api_key,
            401,
            0,
            checked_at,
        ),
        sunday_llm::ProbeOutcome::Status(code) => status_entry(
            "error",
            format!("端点返回 http {code}"),
            latency,
            used_api_key,
            *code,
            0,
            checked_at,
        ),
    }
}

fn probe_reply(status: Value) -> Value {
    let checked_at = status.get("checked_at").cloned().unwrap_or(Value::Null);
    json!({
        "providers": { PROVIDER_ID: status },
        "updated_at": checked_at,
    })
}

/// Removes the key from anything that may be shown or logged.
fn redact(text: &str, key: &str) -> String {
    let key = key.trim();
    if key.is_empty() {
        text.to_owned()
    } else {
        sunday_llm::redact_secret(text, key)
    }
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

    use std::io::{BufRead, BufReader, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};

    /// A real listening socket that records the head of every request it receives.
    ///
    /// The whole point of these tests is what actually goes on the wire, so the
    /// endpoint is a socket rather than a mock: a mock would agree with whatever the
    /// code believes it is doing.
    struct FakeEndpoint {
        port: u16,
        seen: Arc<Mutex<Vec<String>>>,
    }

    impl FakeEndpoint {
        fn start(status: u16, body: &'static str) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
            let port = listener.local_addr().unwrap().port();
            let seen = Arc::new(Mutex::new(Vec::new()));
            let recorded = Arc::clone(&seen);
            std::thread::spawn(move || {
                for stream in listener.incoming() {
                    let mut stream = match stream {
                        Ok(stream) => stream,
                        Err(_) => break,
                    };
                    let mut reader = BufReader::new(stream.try_clone().unwrap());
                    let mut head = String::new();
                    loop {
                        let mut line = String::new();
                        match reader.read_line(&mut line) {
                            Ok(0) | Err(_) => break,
                            Ok(_) => {}
                        }
                        if line == "\r\n" || line == "\n" {
                            break;
                        }
                        head.push_str(&line);
                    }
                    recorded.lock().unwrap().push(head);
                    let reason = match status {
                        200 => "OK",
                        401 => "Unauthorized",
                        _ => "Status",
                    };
                    let response = format!(
                        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                        body.len()
                    );
                    let _ = stream.write_all(response.as_bytes());
                }
            });
            Self { port, seen }
        }

        fn heads(&self) -> Vec<String> {
            self.seen.lock().unwrap().clone()
        }

        fn base_url(&self) -> String {
            format!("http://127.0.0.1:{}/v1", self.port)
        }
    }

    /// A socket that completes the handshake and then never answers.
    ///
    /// Binding and releasing a port was the obvious way to get "nothing there" and
    /// the wrong one: the release makes the port available, and a parallel test's
    /// listener may take it, so the "closed" address sometimes answered. Holding the
    /// socket without accepting keeps the address genuinely unresponsive.
    struct SilentEndpoint {
        port: u16,
        _listener: TcpListener,
    }

    impl SilentEndpoint {
        fn start() -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").expect("bind");
            let port = listener.local_addr().unwrap().port();
            Self {
                port,
                _listener: listener,
            }
        }

        fn base_url(&self) -> String {
            format!("http://127.0.0.1:{}/v1", self.port)
        }
    }

    fn seed(dir: &Path, base_url: &str, confirm: bool) {
        let mut config = load_dir(dir).unwrap();
        config.base_url = base_url.to_owned();
        config.allow_insecure_local = true;
        config.confirm_endpoint = confirm;
        store_dir(dir, &config).unwrap();
        sunday_platform::SecretStore::set(
            &crate::secrets::HostSecrets::new(dir),
            crate::secrets::API_KEY_NAME,
            "sk-live-0123456789",
        )
        .unwrap();
    }

    fn carries_key(head: &str) -> bool {
        head.to_lowercase().contains("authorization")
    }

    /// The regression this whole change exists for: an address nobody approved must
    /// never see the stored key.
    ///
    /// The first request has to be credential-free; only after that request proves
    /// something answers may the second one carry the key.
    #[tokio::test]
    async fn an_unapproved_endpoint_receives_no_key_on_the_first_contact() {
        let server = FakeEndpoint::start(200, r#"{"data":[{"id":"m1"}]}"#);
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), &server.base_url(), false);

        let reply = probe_at(dir.path(), &json!({})).await.unwrap();
        assert_eq!(reply["providers"][PROVIDER_ID]["state"], "ok");

        let heads = server.heads();
        assert!(!heads.is_empty(), "the probe never reached the endpoint");
        assert!(
            !carries_key(&heads[0]),
            "an unapproved address received the key: {}",
            heads[0]
        );
        assert!(
            heads.len() >= 2 && carries_key(&heads[1]),
            "the authenticated probe never followed the approval: {heads:?}"
        );
    }

    /// Changing the address must drop the approval, so the new host gets the same
    /// credential-free treatment as a brand-new one.
    #[tokio::test]
    async fn editing_the_address_stops_the_key_from_following_it() {
        let trusted = FakeEndpoint::start(200, r#"{"data":[]}"#);
        let elsewhere = FakeEndpoint::start(200, r#"{"data":[]}"#);
        let dir = tempfile::tempdir().unwrap();

        // Approved against the first address.
        seed(dir.path(), &trusted.base_url(), false);
        probe_at(dir.path(), &json!({})).await.unwrap();
        let mut config = load_dir(dir.path()).unwrap();
        assert!(
            config.confirm_endpoint,
            "a reachable endpoint earned no approval"
        );

        // The user edits the address. `write_provider` drops the approval; do the same
        // here so the test proves the probe honours it rather than the editor does.
        config.base_url = elsewhere.base_url();
        config.confirm_endpoint = false;
        store_dir(dir.path(), &config).unwrap();

        probe_at(dir.path(), &json!({})).await.unwrap();
        let heads = elsewhere.heads();
        assert!(!heads.is_empty(), "the new address was never probed");
        assert!(
            !carries_key(&heads[0]),
            "the key followed the address change: {}",
            heads[0]
        );
    }

    /// Silence earns nothing: an address that does not answer must not be approved,
    /// because approval is what unlocks the key.
    #[tokio::test]
    async fn an_unreachable_endpoint_is_never_approved() {
        let silent = SilentEndpoint::start();
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), &silent.base_url(), false);

        let reply = probe_at_timeout(dir.path(), &json!({}), Duration::from_millis(400))
            .await
            .unwrap();
        assert_eq!(reply["providers"][PROVIDER_ID]["state"], "unreachable");
        assert!(
            !load_dir(dir.path()).unwrap().confirm_endpoint,
            "an endpoint that never answered was approved anyway"
        );
    }

    /// The gate refuses before the socket is opened, so a public plain-http host is
    /// not merely unauthenticated, it is never contacted.
    #[tokio::test]
    async fn a_public_plain_http_endpoint_is_refused_without_any_request() {
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), "http://api.example.com/v1", false);

        let reply = probe_at(dir.path(), &json!({})).await.unwrap();
        assert_eq!(reply["providers"][PROVIDER_ID]["state"], "invalid");
        assert_eq!(reply["providers"][PROVIDER_ID]["used_api_key"], false);
    }

    /// A refusal still proves a server is there, so the address may be approved and
    /// the key may follow; the reply must not echo the key while saying so.
    #[tokio::test]
    async fn a_refused_key_is_reported_without_leaking_it() {
        let server = FakeEndpoint::start(401, r#"{"error":"bad key sk-live-0123456789"}"#);
        let dir = tempfile::tempdir().unwrap();
        seed(dir.path(), &server.base_url(), false);

        let reply = probe_at(dir.path(), &json!({})).await.unwrap();
        let rendered = reply.to_string();
        assert!(
            !rendered.contains("sk-live-0123456789"),
            "the probe reply leaked the key: {rendered}"
        );
        // The address answered, so it was approved and the key was tried; the final
        // word is then about the credential, which is exactly what a user needs to see.
        assert!(
            load_dir(dir.path()).unwrap().confirm_endpoint,
            "a reachable endpoint did not earn approval"
        );
        assert_eq!(reply["providers"][PROVIDER_ID]["state"], "unauthorized");
    }

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
