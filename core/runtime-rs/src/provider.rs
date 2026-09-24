use crate::profiles::{apply_request_profile, resolve_profile};
use crate::{
    ImageInput, Message, ModelBackend, ModelTurn, RuntimeError, ToolCall, ToolDefinition,
    TurnOptions, MAX_MODEL_IMAGES, MAX_MODEL_IMAGE_BYTES, MAX_MODEL_IMAGE_TOTAL_BYTES,
};
use async_trait::async_trait;
use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::error::Error as StdError;
use std::io;
use std::sync::{Arc, RwLock};
use std::time::Duration;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(15);
const RESPONSE_HEADER_WAIT_MARKER: Duration = Duration::from_secs(30);
const RESPONSE_HEADER_TIMEOUT: Duration = Duration::from_secs(120);

enum HeaderSendError {
    Timeout,
    Transport(reqwest::Error),
    TaskPanicked,
    TaskCancelled,
}

/// Abort the request if its waiter is cancelled or reaches its deadline.
struct AbortSendOnDrop<T>(tokio::task::JoinHandle<T>);

impl<T> Drop for AbortSendOnDrop<T> {
    fn drop(&mut self) {
        self.0.abort();
    }
}

async fn send_until_headers_with_marker(
    mut send: AbortSendOnDrop<Result<reqwest::Response, reqwest::Error>>,
    timeout: Duration,
    marker_after: Duration,
    on_waiting: impl FnOnce(),
) -> Result<reqwest::Response, HeaderSendError> {
    let wait = tokio::time::timeout(timeout, &mut send.0);
    tokio::pin!(wait);
    tokio::select! {
        result = &mut wait => classify_send_result(result),
        _ = tokio::time::sleep(marker_after) => {
            on_waiting();
            classify_send_result(wait.await)
        }
    }
}

fn classify_send_result(
    result: Result<
        Result<Result<reqwest::Response, reqwest::Error>, tokio::task::JoinError>,
        tokio::time::error::Elapsed,
    >,
) -> Result<reqwest::Response, HeaderSendError> {
    result
        .map_err(|_| HeaderSendError::Timeout)?
        .map_err(|error| {
            if error.is_panic() {
                HeaderSendError::TaskPanicked
            } else {
                HeaderSendError::TaskCancelled
            }
        })?
        .map_err(HeaderSendError::Transport)
}

/// Report only fixed diagnostics: reqwest's Display/Debug includes the request
/// URL, and an error source may include proxy credentials or server details.
fn connection_failure_detail(source: &(dyn StdError + 'static), dns_error: bool) -> &'static str {
    if dns_error {
        return "provider DNS lookup failed before response headers (check network or DNS)";
    }
    let mut current = Some(source);
    let mut io_kind = None;
    let mut proxy = false;
    let mut certificate = false;
    let mut cert_expired = false;
    let mut cert_not_yet_valid = false;
    let mut cert_unknown_issuer = false;
    let mut cert_name_mismatch = false;
    let mut cert_revoked = false;
    let mut tls = false;
    while let Some(error) = current {
        if let Some(io_error) = error.downcast_ref::<io::Error>() {
            io_kind = Some(io_error.kind());
        }
        let description = error.to_string().to_ascii_lowercase();
        proxy |= description.contains("proxy") || description.contains("tunnel");
        certificate |= description.contains("certificate")
            || description.contains("unknownissuer")
            || description.contains("certnotvalid");
        cert_expired |= description.contains("certificate") && description.contains("expired");
        cert_not_yet_valid |=
            description.contains("notvalidyet") || description.contains("not valid yet");
        cert_unknown_issuer |=
            description.contains("unknownissuer") || description.contains("unknown issuer");
        cert_name_mismatch |= description.contains("notvalidforname")
            || description.contains("not valid for name")
            || description.contains("invalid dnsname");
        cert_revoked |= description.contains("certificate") && description.contains("revoked");
        tls |= description.contains("tls") || description.contains("rustls");
        current = error.source();
    }
    if proxy {
        "provider proxy connection failed before response headers (check proxy settings)"
    } else if cert_expired {
        "provider TLS certificate expired before response headers (check device clock)"
    } else if cert_not_yet_valid {
        "provider TLS certificate not yet valid before response headers (check device clock)"
    } else if cert_unknown_issuer {
        "provider TLS certificate issuer is not trusted before response headers (check device trust store or network interception)"
    } else if cert_name_mismatch {
        "provider TLS certificate hostname mismatch before response headers (check provider URL or network interception)"
    } else if cert_revoked {
        "provider TLS certificate revocation check failed before response headers"
    } else if certificate {
        "provider TLS certificate verification failed before response headers (check device clock and trusted certificates)"
    } else if tls {
        "provider TLS handshake failed before response headers (check network and TLS settings)"
    } else {
        match io_kind {
            Some(io::ErrorKind::ConnectionRefused) => {
                "provider TCP connection refused before response headers (check server or network)"
            }
            Some(io::ErrorKind::NetworkUnreachable | io::ErrorKind::HostUnreachable) => {
                "provider network unreachable before response headers (check network access)"
            }
            Some(io::ErrorKind::TimedOut) => {
                "provider connection timed out before response headers (check network access)"
            }
            _ => "provider connection failed before response headers (DNS/TCP/TLS/proxy cause unknown)",
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ProviderConfig {
    pub api_type: String,
    pub base_url: String,
    pub api_key: String,
    pub api_model_id: String,
    pub max_output_tokens: Option<u32>,
    pub temperature: Option<f64>,
    #[serde(default)]
    pub provider_name: String,
    #[serde(default)]
    pub provider_extra: Value,
    #[serde(default)]
    pub model_extra: Value,
    #[serde(default)]
    pub thinking_supported: bool,
    pub thinking_budget: Option<u32>,
    #[serde(default)]
    pub notes: String,
}

/// Transport retry policy, mirroring `DEFAULT_MODEL_RETRY_CONFIG` in the
/// Python `config/retry_store.py` so both hosts bound a model attempt the same
/// way.  Without a request timeout a stalled connection never returns and the
/// turn hangs with neither a result nor an error.
#[derive(Clone, Debug)]
pub struct RetryPolicy {
    /// Total attempts, including the first.
    pub attempts: usize,
    /// Timeout for one attempt; covers connect, send and read.
    pub timeout: Duration,
    /// Wait before retry *i*; the last value repeats once the list is exhausted.
    pub delays: Vec<f64>,
    /// Spread each wait by a random 0.5x-1.5x factor.
    pub jitter: bool,
    /// Additional model turns after a successful but empty completion.
    pub empty_response_retries: usize,
    /// Maximum silence between streaming network chunks; None disables it.
    pub stream_idle_timeout: Option<Duration>,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            attempts: 10,
            timeout: Duration::from_secs(360),
            delays: vec![1.0, 1.0, 2.0, 5.0, 5.0],
            jitter: true,
            empty_response_retries: 3,
            stream_idle_timeout: Some(Duration::from_secs(120)),
        }
    }
}

impl RetryPolicy {
    /// Accept the validated `model_retry.jsonc` shape at the mobile host
    /// boundary. Invalid or missing fields retain the shared defaults.
    pub fn from_config(value: &Value) -> Self {
        let mut policy = Self::default();
        if let Some(n) = value
            .get("model_retries")
            .and_then(Value::as_u64)
            .filter(|n| *n > 0)
        {
            policy.attempts = usize::try_from(n).unwrap_or(usize::MAX);
        }
        if let Some(n) = value
            .get("model_timeout_seconds")
            .and_then(Value::as_f64)
            .filter(|n| valid_policy_seconds(*n))
        {
            policy.timeout = Duration::from_secs_f64(n);
        }
        if value
            .get("model_stream_idle_timeout_seconds")
            .is_some_and(Value::is_null)
        {
            policy.stream_idle_timeout = None;
        } else if let Some(n) = value
            .get("model_stream_idle_timeout_seconds")
            .and_then(Value::as_f64)
            .filter(|n| valid_policy_seconds(*n))
        {
            policy.stream_idle_timeout = Some(Duration::from_secs_f64(n));
        }
        if let Some(n) = value.get("empty_response_retries").and_then(Value::as_u64) {
            policy.empty_response_retries = usize::try_from(n).unwrap_or(usize::MAX);
        }
        if let Some(delays) = value.get("retry_delays_seconds").and_then(Value::as_array) {
            let delays: Vec<f64> = delays
                .iter()
                .filter_map(Value::as_f64)
                .filter(|n| n.is_finite() && *n >= 0.0 && *n < 1e12)
                .collect();
            if !delays.is_empty() {
                policy.delays = delays;
            }
        }
        if let Some(jitter) = value.get("jitter").and_then(Value::as_bool) {
            policy.jitter = jitter;
        }
        policy
    }
    /// Seconds to wait before the retry that follows `attempt` failures.
    fn delay_seconds(&self, attempt: usize) -> f64 {
        let base = self
            .delays
            .get(attempt)
            .copied()
            .unwrap_or_else(|| self.delays.last().copied().unwrap_or(0.0));
        if self.jitter {
            base * jitter_factor()
        } else {
            base
        }
    }
}

fn valid_policy_seconds(seconds: f64) -> bool {
    seconds.is_finite() && seconds > 0.0 && seconds < 1e12
}

/// A 0.5x-1.5x factor seeded from the clock; jitter only spreads retries.
fn jitter_factor() -> f64 {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.subsec_nanos())
        .unwrap_or(0);
    0.5 + f64::from(nanos % 1_000) / 1_000.0
}

/// One transport attempt, tagged for the retry decision.
enum AttemptOutcome {
    /// Retrying can help: transport failure, timeout, server error or an
    /// unparsable body.
    Retry(RuntimeError),
    /// A connection or pre-header stall gets one more chance, regardless of
    /// the wider policy for HTTP status and response-body failures.
    RetryConnection(RuntimeError),
    /// Retrying cannot help: the provider reported a client-side error.
    Fatal(RuntimeError),
}

pub struct HttpModelBackend {
    client: reqwest::Client,
    config: ProviderConfig,
    profile: Value,
    last_runtime_model_id: RwLock<String>,
    policy: RetryPolicy,
    progress: Option<Arc<dyn Fn(&'static str) + Send + Sync>>,
    stream: Option<Arc<dyn Fn(&'static str, String) + Send + Sync>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ProviderProtocol {
    OpenAiChat,
    OpenAiResponses,
    AnthropicMessages,
    GeminiGenerativeLanguage,
}

impl HttpModelBackend {
    pub fn new(config: ProviderConfig) -> Result<Self, RuntimeError> {
        Self::with_retry_policy(config, RetryPolicy::default())
    }

    /// Build a backend with an explicit transport retry policy.
    pub fn with_retry_policy(
        config: ProviderConfig,
        policy: RetryPolicy,
    ) -> Result<Self, RuntimeError> {
        let profile = resolve_profile(
            &config.api_type,
            &config.base_url,
            &config.api_model_id,
            &config.provider_name,
            &config.provider_extra,
            &config.model_extra,
        );
        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        let protocol = provider_protocol(&config, &profile);
        let direct_anthropic = config.api_type.to_ascii_lowercase().contains("anthropic");
        let bearer_auth = profile.get("auth").and_then(Value::as_str) == Some("bearer");
        if protocol == ProviderProtocol::AnthropicMessages && (direct_anthropic || !bearer_auth) {
            headers.insert(
                "x-api-key",
                HeaderValue::from_str(&config.api_key)
                    .map_err(|error| RuntimeError::Model(error.to_string()))?,
            );
            headers.insert("anthropic-version", HeaderValue::from_static("2023-06-01"));
        } else if protocol == ProviderProtocol::GeminiGenerativeLanguage && !bearer_auth {
            headers.insert(
                "x-goog-api-key",
                HeaderValue::from_str(&config.api_key)
                    .map_err(|error| RuntimeError::Model(error.to_string()))?,
            );
        } else {
            headers.insert(
                AUTHORIZATION,
                HeaderValue::from_str(&format!("Bearer {}", config.api_key))
                    .map_err(|error| RuntimeError::Model(error.to_string()))?,
            );
        }
        // A total timeout is what keeps a stalled turn finite.
        let client = reqwest::Client::builder()
            .default_headers(headers)
            .connect_timeout(policy.timeout.min(CONNECT_TIMEOUT))
            .timeout(policy.timeout)
            .build()
            .map_err(|error| RuntimeError::Model(error.to_string()))?;
        let initial_model_id = config.api_model_id.clone();
        Ok(Self {
            client,
            config,
            profile,
            last_runtime_model_id: RwLock::new(initial_model_id),
            policy,
            progress: None,
            stream: None,
        })
    }

    /// Report transport boundaries without exposing requests, headers or keys.
    /// Mobile debug builds display these markers in the turn transcript.
    pub fn with_progress(mut self, report: impl Fn(&'static str) + Send + Sync + 'static) -> Self {
        self.progress = Some(Arc::new(report));
        self
    }

    /// Provisional model output. The final ModelTurn is always authoritative.
    pub fn with_stream(
        mut self,
        report: impl Fn(&'static str, String) + Send + Sync + 'static,
    ) -> Self {
        self.stream = Some(Arc::new(report));
        self
    }

    fn stream_event(&self, kind: &'static str, delta: String) {
        if let Some(report) = &self.stream {
            report(kind, delta);
        }
    }

    fn report(&self, stage: &'static str) {
        if let Some(report) = &self.progress {
            report(stage);
        }
    }

    fn protocol(&self) -> ProviderProtocol {
        provider_protocol(&self.config, &self.profile)
    }

    fn request_url(&self) -> String {
        let fallback = match self.protocol() {
            ProviderProtocol::AnthropicMessages => "/messages",
            ProviderProtocol::OpenAiResponses => "/responses",
            ProviderProtocol::GeminiGenerativeLanguage => "/v1beta/models/{model}:generateContent",
            ProviderProtocol::OpenAiChat => "/chat/completions",
        };
        let endpoint = self
            .profile
            .get("endpoint")
            .and_then(Value::as_str)
            .unwrap_or(fallback);
        let mut url = join_endpoint(
            &self.config.base_url,
            &endpoint.replace("{model}", &self.config.api_model_id),
        );
        if self.stream.is_some() && self.protocol() == ProviderProtocol::GeminiGenerativeLanguage {
            url = url.replace(":generateContent", ":streamGenerateContent");
            if !url.contains("alt=sse") {
                url.push_str(if url.contains('?') {
                    "&alt=sse"
                } else {
                    "?alt=sse"
                });
            }
        }
        url
    }

    /// Retry a transport failure within the policy budget so a stalled
    /// provider cannot leave a turn running forever.
    async fn send_with_retry(&self, body: &Value) -> Result<Value, RuntimeError> {
        let mut failures = 0usize;
        loop {
            if failures > 0 {
                self.stream_event("reset", String::new());
            }
            match self.send_attempt(body).await {
                Ok(payload) => return Ok(payload),
                Err(AttemptOutcome::Fatal(error)) => return Err(error),
                Err(outcome) => {
                    let (error, max_attempts) = match outcome {
                        AttemptOutcome::Retry(error) => (error, self.policy.attempts.max(1)),
                        AttemptOutcome::RetryConnection(error) => {
                            (error, self.policy.attempts.max(1).min(2))
                        }
                        AttemptOutcome::Fatal(_) => unreachable!(),
                    };
                    failures += 1;
                    if failures >= max_attempts {
                        if self.stream.is_some() {
                            self.stream_event("reset", String::new());
                        }
                        return Err(error);
                    }
                    self.report("http_retry_wait");
                    let delay = self.policy.delay_seconds(failures - 1);
                    if delay > 0.0 {
                        tokio::time::sleep(Duration::from_secs_f64(delay)).await;
                    }
                }
            }
        }
    }

    /// One attempt, classified so the caller knows whether a retry can help.
    async fn send_attempt(&self, body: &Value) -> Result<Value, AttemptOutcome> {
        self.report("http_send_start");
        let request = self
            .client
            .post(self.request_url())
            .json(body)
            .build()
            .map_err(|_| {
                self.report("http_request_build_error");
                AttemptOutcome::Fatal(RuntimeError::Model(
                    "provider request could not be built".into(),
                ))
            })?;
        // Queue the request before emitting the built marker: a slow native
        // progress callback must not prevent the send from starting.
        let client = self.client.clone();
        let send = AbortSendOnDrop(tokio::spawn(async move { client.execute(request).await }));
        self.report("http_request_built");
        let response = send_until_headers_with_marker(
            send,
            self.policy.timeout.min(RESPONSE_HEADER_TIMEOUT),
            RESPONSE_HEADER_WAIT_MARKER,
            || self.report("http_waiting_for_headers"),
        )
        .await;
        let response = response.map_err(|error| {
            let message = match error {
                HeaderSendError::Timeout => {
                    self.report("http_send_timeout");
                    "provider response headers timed out"
                }
                HeaderSendError::Transport(error) if error.is_connect() => {
                    self.report("http_connect_error");
                    connection_failure_detail(error.source().unwrap_or(&error), error.is_dns())
                }
                HeaderSendError::Transport(error) if error.is_timeout() => {
                    self.report("http_send_timeout");
                    "provider request timed out before response headers"
                }
                HeaderSendError::TaskPanicked => {
                    self.report("http_send_task_panicked");
                    return AttemptOutcome::Fatal(RuntimeError::Model(
                        "provider send task panicked".into(),
                    ));
                }
                HeaderSendError::TaskCancelled => {
                    self.report("http_send_task_cancelled");
                    return AttemptOutcome::Fatal(RuntimeError::Model(
                        "provider send task cancelled".into(),
                    ));
                }
                HeaderSendError::Transport(_) => "provider request failed before response headers",
            };
            self.report("http_transport_error");
            AttemptOutcome::RetryConnection(RuntimeError::Model(message.into()))
        })?;
        self.report("http_headers_received");
        let status = response.status();
        if status.is_success() && self.stream.is_some() {
            let payload = match self.protocol() {
                ProviderProtocol::OpenAiChat => {
                    read_openai_stream_with_idle(
                        response,
                        self.stream.as_ref(),
                        self.progress.as_ref(),
                        self.policy.stream_idle_timeout,
                    )
                    .await
                }
                protocol => {
                    read_native_stream(
                        response,
                        protocol,
                        self.stream.as_ref(),
                        self.progress.as_ref(),
                        self.policy.stream_idle_timeout,
                    )
                    .await
                }
            }
            .map_err(|error| {
                self.report("http_transport_error");
                AttemptOutcome::Retry(RuntimeError::Model(error))
            })?;
            self.report("http_body_received");
            self.remember_runtime_model(&payload);
            return Ok(payload);
        }
        let response_text = response.text().await.map_err(|error| {
            self.report("http_transport_error");
            AttemptOutcome::Retry(RuntimeError::Model(error.to_string()))
        })?;
        self.report("http_body_received");
        if !status.is_success() {
            self.report("http_provider_error");
            let payload = serde_json::from_str::<Value>(&response_text).ok();
            let message = payload
                .as_ref()
                .and_then(|payload| payload.pointer("/error/message"))
                .and_then(Value::as_str)
                .unwrap_or("provider request failed");
            let error = RuntimeError::Model(format!("{message} ({status})"));
            // A server error or a rate limit can clear on its own; a 4xx will not.
            return Err(if retryable_status(status) {
                AttemptOutcome::Retry(error)
            } else {
                AttemptOutcome::Fatal(error)
            });
        }
        if response_text.trim().is_empty() {
            return Ok(Value::Null);
        }
        let payload: Value = serde_json::from_str(&response_text).map_err(|error| {
            AttemptOutcome::Retry(RuntimeError::Model(format!(
                "invalid provider response: {error}"
            )))
        })?;
        self.remember_runtime_model(&payload);
        Ok(payload)
    }

    fn remember_runtime_model(&self, payload: &Value) {
        let value = match self.protocol() {
            ProviderProtocol::GeminiGenerativeLanguage => {
                payload.get("modelVersion").or_else(|| payload.get("model"))
            }
            _ => payload.get("model"),
        }
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty());
        if let Some(value) = value {
            if let Ok(mut model_id) = self.last_runtime_model_id.write() {
                *model_id = value.to_owned();
            }
        }
    }
}

/// Assemble OpenAI-compatible SSE into the same shape used by the nonstreaming
/// parser. Tool-call arguments are joined by index before JSON decoding.
async fn read_openai_stream(
    response: reqwest::Response,
    report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
    progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
) -> Result<Value, String> {
    read_openai_stream_with_idle(response, report, progress, None).await
}

async fn read_openai_stream_with_idle(
    mut response: reqwest::Response,
    report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
    progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
    idle_timeout: Option<Duration>,
) -> Result<Value, String> {
    if !response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|v| v.to_str().ok())
        .unwrap_or_default()
        .contains("text/event-stream")
    {
        return response.json::<Value>().await.map_err(|e| e.to_string());
    }
    let mut buffer = Vec::<u8>::new();
    let mut text = String::new();
    let mut reasoning = String::new();
    let mut calls = Vec::<Value>::new();
    let mut model = None::<String>;
    let mut finish_reason = None::<String>;
    let mut pending_text = String::new();
    let mut pending_reasoning = String::new();
    let mut last_emit = std::time::Instant::now();
    let mut done = false;
    let mut reported_streaming = false;
    let mut total_bytes = 0usize;
    while let Some(chunk) = if let Some(idle) = idle_timeout {
        tokio::time::timeout(idle, response.chunk())
            .await
            .map_err(|_| "provider stream idle timeout".to_owned())?
    } else {
        response.chunk().await
    }
    .map_err(|e| e.to_string())?
    {
        total_bytes = total_bytes.saturating_add(chunk.len());
        if total_bytes > MAX_NATIVE_STREAM_BYTES {
            return Err("provider SSE exceeds 32 MiB".into());
        }
        buffer.extend_from_slice(&chunk);
        if buffer.len() > 8 * 1024 * 1024 {
            return Err("provider SSE frame exceeds 8 MiB".into());
        }
        while let Some((end, delimiter)) = sse_frame_boundary(&buffer) {
            let frame = buffer.drain(..end + delimiter).collect::<Vec<_>>();
            let frame = std::str::from_utf8(&frame[..end]).map_err(|e| e.to_string())?;
            let data = frame
                .split(|ch| ch == '\r' || ch == '\n')
                .filter_map(|line| line.strip_prefix("data:"))
                .map(str::trim_start)
                .collect::<Vec<_>>()
                .join("\n");
            if data.is_empty() {
                continue;
            }
            if data == "[DONE]" {
                done = true;
                break;
            }
            let event: Value =
                serde_json::from_str(&data).map_err(|e| format!("invalid provider SSE: {e}"))?;
            if event.get("error").is_some() {
                return Err(event
                    .pointer("/error/message")
                    .and_then(Value::as_str)
                    .unwrap_or("provider streaming error")
                    .to_owned());
            }
            if let Some(name) = event.get("model").and_then(Value::as_str) {
                model = Some(name.to_owned());
            }
            if let Some(reason) = event
                .pointer("/choices/0/finish_reason")
                .and_then(Value::as_str)
            {
                // A later malformed chunk must not turn a truncated result
                // into a completed answer or executable tool call.
                if reason == "length" || finish_reason.as_deref() != Some("length") {
                    finish_reason = Some(reason.to_owned());
                }
            }
            let Some(delta) = event.pointer("/choices/0/delta") else {
                continue;
            };
            if let Some(part) = delta.get("content").and_then(Value::as_str) {
                text.push_str(part);
                pending_text.push_str(part);
            }
            for key in ["reasoning_content", "reasoning", "thinking"] {
                if let Some(part) = delta.get(key).and_then(Value::as_str) {
                    reasoning.push_str(part);
                    pending_reasoning.push_str(part);
                    break;
                }
            }
            if !reported_streaming && (!pending_text.is_empty() || !pending_reasoning.is_empty()) {
                reported_streaming = true;
                if let Some(progress) = progress {
                    progress("http_streaming");
                }
            }
            if let Some(fragments) = delta.get("tool_calls").and_then(Value::as_array) {
                for fragment in fragments {
                    let index = fragment.get("index").and_then(Value::as_u64).unwrap_or(0) as usize;
                    if index > 128 {
                        return Err("too many provider tool calls".into());
                    }
                    while calls.len() <= index {
                        calls.push(json!({"id":"","type":"function","function":{"name":"","arguments":""}}));
                    }
                    let call = &mut calls[index];
                    for (target, source) in
                        [("id", fragment.get("id")), ("type", fragment.get("type"))]
                    {
                        if let Some(value) = source.and_then(Value::as_str) {
                            append_json_string(&mut call[target], value);
                        }
                    }
                    for field in ["name", "arguments"] {
                        if let Some(value) = fragment
                            .pointer(&format!("/function/{field}"))
                            .and_then(Value::as_str)
                        {
                            append_json_string(&mut call["function"][field], value);
                        }
                    }
                }
            }
            if last_emit.elapsed() >= Duration::from_millis(32)
                || pending_text.len() + pending_reasoning.len() >= 256
            {
                flush_stream_pending(report, &mut pending_text, &mut pending_reasoning);
                last_emit = std::time::Instant::now();
            }
        }
        if done {
            break;
        }
    }
    if !done {
        return Err(if buffer.is_empty() {
            "provider SSE ended before [DONE]".into()
        } else {
            "provider SSE ended with incomplete frame".into()
        });
    }
    flush_stream_pending(report, &mut pending_text, &mut pending_reasoning);
    let mut message = json!({"content":text,"tool_calls":calls});
    if !reasoning.is_empty() {
        message["reasoning_content"] = json!(reasoning);
    }
    Ok(json!({"model":model,"choices":[{"message":message,"finish_reason":finish_reason}]}))
}

fn sse_frame_boundary(buffer: &[u8]) -> Option<(usize, usize)> {
    [
        b"\r\n\r\n".as_slice(),
        b"\n\n",
        b"\r\r",
        b"\r\n\n",
        b"\n\r\n",
    ]
    .into_iter()
    .filter_map(|delimiter| {
        buffer
            .windows(delimiter.len())
            .position(|x| x == delimiter)
            .map(|index| (index, delimiter.len()))
    })
    .min_by_key(|(index, _)| *index)
}

fn append_json_string(target: &mut Value, part: &str) {
    let mut value = target.as_str().unwrap_or_default().to_owned();
    value.push_str(part);
    *target = Value::String(value);
}

fn flush_stream_pending(
    report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
    text: &mut String,
    reasoning: &mut String,
) {
    if let Some(report) = report {
        if !text.is_empty() {
            report("text_delta", std::mem::take(text));
        }
        if !reasoning.is_empty() {
            report("reasoning_delta", std::mem::take(reasoning));
        }
    }
}

const MAX_NATIVE_STREAM_BYTES: usize = 32 * 1024 * 1024;

/// Native protocol SSE is assembled into the same payload shape as its JSON
/// endpoint, so the existing model-turn and continuation parsers remain the
/// single source of truth for text, reasoning and tool calls.
async fn read_native_stream(
    mut response: reqwest::Response,
    protocol: ProviderProtocol,
    report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
    progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
    idle_timeout: Option<Duration>,
) -> Result<Value, String> {
    if !response
        .headers()
        .get(CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .unwrap_or_default()
        .contains("text/event-stream")
    {
        return response
            .json::<Value>()
            .await
            .map_err(|error| error.to_string());
    }
    let mut buffer = Vec::<u8>::new();
    let mut total = 0usize;
    let mut accumulator = NativeStream::new(protocol);
    while let Some(chunk) = if let Some(idle) = idle_timeout {
        tokio::time::timeout(idle, response.chunk())
            .await
            .map_err(|_| "provider stream idle timeout".to_owned())?
    } else {
        response.chunk().await
    }
    .map_err(|error| error.to_string())?
    {
        total = total.saturating_add(chunk.len());
        if total > MAX_NATIVE_STREAM_BYTES {
            return Err("provider SSE exceeds 32 MiB".into());
        }
        buffer.extend_from_slice(&chunk);
        if buffer.len() > 8 * 1024 * 1024 {
            return Err("provider SSE frame exceeds 8 MiB".into());
        }
        while let Some((end, delimiter)) = sse_frame_boundary(&buffer) {
            let frame = buffer.drain(..end + delimiter).collect::<Vec<_>>();
            let frame = std::str::from_utf8(&frame[..end]).map_err(|error| error.to_string())?;
            let mut event_name = "";
            let mut data_lines = Vec::new();
            for line in frame.split(|ch| ch == '\r' || ch == '\n') {
                if let Some(name) = line.strip_prefix("event:") {
                    event_name = name.trim();
                }
                if let Some(data) = line.strip_prefix("data:") {
                    data_lines.push(data.trim_start());
                }
            }
            let data = data_lines.join("\n");
            if data.is_empty() {
                continue;
            }
            if data == "[DONE]" {
                accumulator.sentinel()?;
            } else {
                let event: Value = serde_json::from_str(&data)
                    .map_err(|error| format!("invalid provider SSE: {error}"))?;
                accumulator.ingest(&event, event_name, report, progress)?;
            }
            if accumulator.done {
                return accumulator.finish();
            }
        }
    }
    Err(if buffer.is_empty() {
        "provider SSE ended before terminal event".into()
    } else {
        "provider SSE ended with incomplete frame".into()
    })
}

struct NativeStream {
    protocol: ProviderProtocol,
    payload: Value,
    tool_inputs: Vec<String>,
    open_blocks: Vec<bool>,
    done: bool,
    reported_streaming: bool,
}

impl NativeStream {
    fn new(protocol: ProviderProtocol) -> Self {
        let payload = match protocol {
            ProviderProtocol::AnthropicMessages => json!({"content":[],"stop_reason":null}),
            ProviderProtocol::OpenAiResponses => json!({"output":[]}),
            ProviderProtocol::GeminiGenerativeLanguage => {
                json!({"candidates":[{"content":{"role":"model","parts":[]}}]})
            }
            ProviderProtocol::OpenAiChat => Value::Null,
        };
        Self {
            protocol,
            payload,
            tool_inputs: Vec::new(),
            open_blocks: Vec::new(),
            done: false,
            reported_streaming: false,
        }
    }

    fn delta(
        &mut self,
        kind: &'static str,
        value: &str,
        report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
        progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
    ) {
        if value.is_empty() {
            return;
        }
        if !self.reported_streaming {
            self.reported_streaming = true;
            if let Some(progress) = progress {
                progress("http_streaming");
            }
        }
        if let Some(report) = report {
            report(kind, value.to_owned());
        }
    }

    fn sentinel(&mut self) -> Result<(), String> {
        match self.protocol {
            ProviderProtocol::GeminiGenerativeLanguage
                if self.payload.pointer("/candidates/0/finishReason").is_some() =>
            {
                self.done = true;
                Ok(())
            }
            _ if self.done => Ok(()),
            _ => Err("provider SSE ended before terminal event".into()),
        }
    }

    fn ingest(
        &mut self,
        event: &Value,
        sse_name: &str,
        report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
        progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
    ) -> Result<(), String> {
        if let Some(message) = event.pointer("/error/message").and_then(Value::as_str) {
            return Err(message.to_owned());
        }
        match self.protocol {
            ProviderProtocol::AnthropicMessages => {
                self.anthropic(event, sse_name, report, progress)
            }
            ProviderProtocol::OpenAiResponses => self.responses(event, sse_name, report, progress),
            ProviderProtocol::GeminiGenerativeLanguage => self.gemini(event, report, progress),
            ProviderProtocol::OpenAiChat => unreachable!(),
        }
    }

    fn anthropic(
        &mut self,
        event: &Value,
        sse_name: &str,
        report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
        progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
    ) -> Result<(), String> {
        let kind = event
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or(sse_name);
        match kind {
            "message_start" => {
                if let Some(model) = event.pointer("/message/model") {
                    self.payload["model"] = model.clone();
                }
            }
            "content_block_start" => {
                let index = stream_index(event, "index")?;
                let block = event.get("content_block").cloned().unwrap_or(Value::Null);
                let blocks = self.payload["content"].as_array_mut().unwrap();
                if index != blocks.len() {
                    return Err("out-of-order Anthropic content block".into());
                }
                blocks.push(block);
                self.tool_inputs.push(String::new());
                self.open_blocks.push(true);
            }
            "content_block_delta" => {
                let index = stream_index(event, "index")?;
                let delta = event.get("delta").ok_or("missing Anthropic delta")?;
                let kind = delta.get("type").and_then(Value::as_str).unwrap_or("");
                match kind {
                    "text_delta" | "thinking_delta" | "signature_delta" => {
                        let (field, source, report_kind) = match kind {
                            "text_delta" => ("text", "text", "text_delta"),
                            "thinking_delta" => ("thinking", "thinking", "reasoning_delta"),
                            _ => ("signature", "signature", ""),
                        };
                        let part = delta.get(source).and_then(Value::as_str).unwrap_or("");
                        let block = self.payload["content"]
                            .get_mut(index)
                            .ok_or("unknown Anthropic block")?;
                        append_json_string(&mut block[field], part);
                        if !report_kind.is_empty() {
                            self.delta(report_kind, part, report, progress);
                        }
                    }
                    "input_json_delta" => {
                        let part = delta
                            .get("partial_json")
                            .and_then(Value::as_str)
                            .unwrap_or("");
                        self.tool_inputs
                            .get_mut(index)
                            .ok_or("unknown Anthropic tool block")?
                            .push_str(part);
                    }
                    _ => {}
                }
            }
            "content_block_stop" => {
                let index = stream_index(event, "index")?;
                *self
                    .open_blocks
                    .get_mut(index)
                    .ok_or("unknown Anthropic block")? = false;
                if let Some(raw) = self.tool_inputs.get(index).filter(|raw| !raw.is_empty()) {
                    self.payload["content"][index]["input"] = serde_json::from_str(raw)
                        .map_err(|_| "incomplete Anthropic tool arguments")?;
                }
            }
            "message_delta" => {
                if let Some(reason) = event.pointer("/delta/stop_reason") {
                    self.payload["stop_reason"] = reason.clone();
                }
            }
            "message_stop" => {
                self.done = true;
            }
            "error" => return Err("provider streaming error".into()),
            _ => {}
        }
        Ok(())
    }

    fn responses(
        &mut self,
        event: &Value,
        sse_name: &str,
        report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
        progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
    ) -> Result<(), String> {
        let kind = event
            .get("type")
            .and_then(Value::as_str)
            .unwrap_or(sse_name);
        match kind {
            "response.created" | "response.in_progress" => {
                if let Some(model) = event.pointer("/response/model") {
                    self.payload["model"] = model.clone();
                }
            }
            "response.output_item.added" | "response.output_item.done" => {
                let index = stream_index(event, "output_index")?;
                let item = event
                    .get("item")
                    .cloned()
                    .ok_or("missing Responses output item")?;
                let output = self.payload["output"].as_array_mut().unwrap();
                if index > output.len() {
                    return Err("out-of-order Responses output item".into());
                }
                if index == output.len() {
                    output.push(item);
                } else {
                    output[index] = item;
                }
            }
            "response.output_text.delta"
            | "response.reasoning_summary_text.delta"
            | "response.function_call_arguments.delta" => {
                let index = stream_index(event, "output_index")?;
                let part = event.get("delta").and_then(Value::as_str).unwrap_or("");
                let item = self.payload["output"]
                    .get_mut(index)
                    .ok_or("unknown Responses output item")?;
                match kind {
                    "response.output_text.delta" => {
                        let content_index = event
                            .get("content_index")
                            .and_then(Value::as_u64)
                            .unwrap_or(0) as usize;
                        if content_index > 128 {
                            return Err("too many Responses content parts".into());
                        }
                        let content = item["content"]
                            .as_array_mut()
                            .ok_or("missing Responses message content")?;
                        while content.len() <= content_index {
                            content.push(json!({"type":"output_text","text":""}));
                        }
                        append_json_string(&mut content[content_index]["text"], part);
                        self.delta("text_delta", part, report, progress);
                    }
                    "response.reasoning_summary_text.delta" => {
                        let summary_index = event
                            .get("summary_index")
                            .and_then(Value::as_u64)
                            .unwrap_or(0) as usize;
                        if summary_index > 128 {
                            return Err("too many Responses summaries".into());
                        }
                        let summaries = item["summary"]
                            .as_array_mut()
                            .ok_or("missing Responses summary")?;
                        while summaries.len() <= summary_index {
                            summaries.push(json!({"type":"summary_text","text":""}));
                        }
                        append_json_string(&mut summaries[summary_index]["text"], part);
                        self.delta("reasoning_delta", part, report, progress);
                    }
                    _ => append_json_string(&mut item["arguments"], part),
                }
            }
            "response.completed" => {
                if let Some(response) = event.get("response") {
                    self.payload = response.clone();
                }
                self.done = true;
            }
            "response.failed" | "response.incomplete" => {
                return Err(format!("provider Responses stream {kind}"))
            }
            "error" => return Err("provider streaming error".into()),
            _ => {}
        }
        Ok(())
    }

    fn gemini(
        &mut self,
        event: &Value,
        report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
        progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
    ) -> Result<(), String> {
        if let Some(model) = event.get("modelVersion") {
            self.payload["modelVersion"] = model.clone();
        }
        if let Some(candidate) = event.pointer("/candidates/0") {
            if let Some(parts) = candidate
                .pointer("/content/parts")
                .and_then(Value::as_array)
            {
                for part in parts {
                    if self.payload["candidates"][0]["content"]["parts"]
                        .as_array()
                        .unwrap()
                        .len()
                        >= 4096
                    {
                        return Err("too many Gemini stream parts".into());
                    }
                    let text = part.get("text").and_then(Value::as_str).unwrap_or("");
                    if part.get("thought").and_then(Value::as_bool) == Some(true) {
                        self.delta("reasoning_delta", text, report, progress);
                    } else {
                        self.delta("text_delta", text, report, progress);
                    }
                    self.payload["candidates"][0]["content"]["parts"]
                        .as_array_mut()
                        .unwrap()
                        .push(part.clone());
                }
            }
            if let Some(reason) = candidate.get("finishReason") {
                self.payload["candidates"][0]["finishReason"] = reason.clone();
                self.done = true;
            }
        }
        Ok(())
    }

    fn finish(self) -> Result<Value, String> {
        match self.protocol {
            ProviderProtocol::AnthropicMessages => {
                if self.open_blocks.iter().any(|open| *open) {
                    return Err("Anthropic stream ended with unfinished content block".into());
                }
                if self.payload["stop_reason"] == "max_tokens" {
                    return Err("provider output truncated at max_tokens".into());
                }
                if self.payload["stop_reason"].is_null() {
                    return Err("Anthropic stream missing stop reason".into());
                }
            }
            ProviderProtocol::OpenAiResponses => {
                if self.payload.get("status").and_then(Value::as_str) != Some("completed") {
                    return Err("Responses stream did not complete".into());
                }
                if let Some(output) = self.payload.get("output").and_then(Value::as_array) {
                    for item in output {
                        if item.get("type").and_then(Value::as_str) == Some("function_call") {
                            let raw = item
                                .get("arguments")
                                .and_then(Value::as_str)
                                .ok_or("Responses tool arguments missing")?;
                            if !serde_json::from_str::<Value>(raw)
                                .is_ok_and(|args| args.is_object())
                            {
                                return Err("incomplete Responses tool arguments".into());
                            }
                        }
                    }
                }
            }
            ProviderProtocol::GeminiGenerativeLanguage => {
                let reason = self
                    .payload
                    .pointer("/candidates/0/finishReason")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if !matches!(reason, "STOP" | "FINISH_REASON_UNSPECIFIED") {
                    return Err(format!("Gemini stream stopped with {reason}"));
                }
            }
            ProviderProtocol::OpenAiChat => unreachable!(),
        }
        Ok(self.payload)
    }
}

fn stream_index(event: &Value, key: &str) -> Result<usize, String> {
    let index = event
        .get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("missing provider {key}"))?;
    if index > 128 {
        return Err("too many provider stream items".into());
    }
    Ok(index as usize)
}

fn messages_with_model_notes(messages: &[Message], notes: &str) -> Vec<Message> {
    let notes = notes.trim();
    if notes.is_empty() {
        return messages.to_vec();
    }
    let note_block = format!("Current model notes: {notes}");
    let mut updated = messages.to_vec();
    if let Some(index) = updated
        .iter()
        .position(|message| matches!(message, Message::System { .. }))
    {
        if let Message::System { content } = &mut updated[index] {
            if !content.contains(&note_block) {
                if !content.is_empty() && !content.ends_with('\n') {
                    content.push('\n');
                }
                content.push_str(&note_block);
            }
        }
    } else {
        updated.insert(
            0,
            Message::System {
                content: note_block,
            },
        );
    }
    updated
}

#[async_trait]
impl ModelBackend for HttpModelBackend {
    async fn complete(
        &self,
        _model_record_id: &str,
        messages: &[Message],
        tools: &[ToolDefinition],
        options: &TurnOptions,
    ) -> Result<ModelTurn, RuntimeError> {
        let protocol = self.protocol();
        let mut request_messages = messages_with_model_notes(messages, &self.config.notes);
        validate_model_images(&request_messages)?;
        for empty_attempt in 0..=self.policy.empty_response_retries {
            let mut body = match protocol {
                ProviderProtocol::AnthropicMessages => anthropic_body(
                    &self.config,
                    &self.profile,
                    &request_messages,
                    tools,
                    options,
                ),
                ProviderProtocol::OpenAiResponses => responses_body(
                    &self.config,
                    &self.profile,
                    &request_messages,
                    tools,
                    options,
                ),
                ProviderProtocol::GeminiGenerativeLanguage => gemini_body(
                    &self.config,
                    &self.profile,
                    &request_messages,
                    tools,
                    options,
                ),
                ProviderProtocol::OpenAiChat => openai_body(
                    &self.config,
                    &self.profile,
                    &request_messages,
                    tools,
                    options,
                ),
            };
            // Profiles can override body fields; select the wire format last.
            if protocol == ProviderProtocol::GeminiGenerativeLanguage {
                if let Some(fields) = body.as_object_mut() {
                    fields.remove("stream");
                }
            } else {
                body["stream"] = Value::Bool(self.stream.is_some());
            }
            if empty_attempt > 0 {
                self.stream_event("reset", String::new());
            }
            let payload = self.send_with_retry(&body).await?;
            let turn = match protocol {
                ProviderProtocol::AnthropicMessages => parse_anthropic(
                    payload,
                    &self.config.api_model_id,
                    profile_id(&self.profile),
                ),
                ProviderProtocol::OpenAiResponses => parse_responses(
                    payload,
                    &self.config.api_model_id,
                    profile_id(&self.profile),
                ),
                ProviderProtocol::GeminiGenerativeLanguage => parse_gemini(
                    payload,
                    &self.config.api_model_id,
                    profile_id(&self.profile),
                ),
                ProviderProtocol::OpenAiChat => parse_openai(
                    payload,
                    &self.config.api_model_id,
                    profile_id(&self.profile),
                ),
            }
            .map_err(|error| {
                if self.stream.is_some() {
                    self.stream_event("reset", String::new());
                }
                error
            })?;
            match turn {
                ModelTurn::Text {
                    ref text,
                    ref provider_state,
                    ..
                } if text.trim().is_empty() => {
                    if empty_attempt == self.policy.empty_response_retries {
                        break;
                    }
                    // Carry protocol-specific reasoning state into the next
                    // request, while keeping the retry instruction ephemeral.
                    request_messages.push(Message::Assistant {
                        content: text.clone(),
                        provider_state: provider_state.clone(),
                    });
                    request_messages.push(Message::User {
                        content: "The previous model turn stopped with no final text and no tool calls. Continue the task now: either call the needed tools or provide a visible failure reason if the task cannot proceed.".into(),
                    });
                }
                _ => return Ok(turn),
            }
        }
        Err(RuntimeError::Model(format!(
            "Model stopped with no content after {} retries.",
            self.policy.empty_response_retries
        )))
    }

    fn runtime_model_id(&self, _model_record_id: &str) -> String {
        self.last_runtime_model_id
            .read()
            .map(|model_id| model_id.clone())
            .unwrap_or_else(|_| self.config.api_model_id.clone())
    }
}

fn validate_model_images(messages: &[Message]) -> Result<(), RuntimeError> {
    let mut total_bytes = 0usize;
    for message in messages {
        let Message::UserMultimodal { images, .. } = message else {
            continue;
        };
        if images.is_empty() || images.len() > MAX_MODEL_IMAGES {
            return Err(RuntimeError::Model(format!(
                "image input must contain between 1 and {MAX_MODEL_IMAGES} images"
            )));
        }
        for image in images {
            if image.attachment_id.trim().is_empty() {
                return Err(RuntimeError::Model(
                    "image input is missing its durable attachment ID".into(),
                ));
            }
            if !matches!(
                image.mime_type.as_str(),
                "image/jpeg" | "image/png" | "image/gif" | "image/webp"
            ) {
                return Err(RuntimeError::Model(format!(
                    "unsupported image MIME type: {}",
                    image.mime_type
                )));
            }
            let decoded_bytes = checked_base64_size(&image.data_base64).ok_or_else(|| {
                RuntimeError::Model("image input is missing valid base64 bytes".into())
            })?;
            if decoded_bytes > MAX_MODEL_IMAGE_BYTES {
                return Err(RuntimeError::Model(format!(
                    "image exceeds the {} MiB model-input limit",
                    MAX_MODEL_IMAGE_BYTES / (1024 * 1024)
                )));
            }
            total_bytes = total_bytes.saturating_add(decoded_bytes);
            if total_bytes > MAX_MODEL_IMAGE_TOTAL_BYTES {
                return Err(RuntimeError::Model(format!(
                    "conversation images exceed the {} MiB model-input limit",
                    MAX_MODEL_IMAGE_TOTAL_BYTES / (1024 * 1024)
                )));
            }
        }
    }
    Ok(())
}

fn checked_base64_size(value: &str) -> Option<usize> {
    let bytes = value.as_bytes();
    if bytes.is_empty() || bytes.len() % 4 != 0 {
        return None;
    }
    let padding = bytes.iter().rev().take_while(|byte| **byte == b'=').count();
    if padding > 2 {
        return None;
    }
    let payload_end = bytes.len().checked_sub(padding)?;
    if bytes[..payload_end]
        .iter()
        .any(|byte| !byte.is_ascii_alphanumeric() && !matches!(*byte, b'+' | b'/'))
        || bytes[payload_end..].iter().any(|byte| *byte != b'=')
    {
        return None;
    }
    match padding {
        0 => {}
        1 if payload_end % 4 == 3 => {}
        2 if payload_end % 4 == 2 => {}
        _ => return None,
    }
    bytes
        .len()
        .checked_div(4)?
        .checked_mul(3)?
        .checked_sub(padding)
}

fn openai_image_data_url(image: &ImageInput) -> String {
    format!("data:{};base64,{}", image.mime_type, image.data_base64)
}

fn openai_body(
    config: &ProviderConfig,
    profile: &Value,
    messages: &[Message],
    tools: &[ToolDefinition],
    options: &TurnOptions,
) -> Value {
    let messages = messages
        .iter()
        .map(|message| openai_message(message, &config.api_model_id, profile_id(profile)))
        .collect::<Vec<_>>();
    let converted_tools = tools
        .iter()
        .map(|tool| {
            json!({
                "type": "function",
                "function": { "name": tool.name, "description": tool.description, "parameters": tool.input_schema },
            })
        })
        .collect::<Vec<_>>();
    let mut body = json!({
        "model": config.api_model_id,
        "messages": messages,
        "stream": false,
    });
    if !converted_tools.is_empty() {
        body["tools"] = json!(converted_tools);
        body["tool_choice"] = json!("auto");
    }
    if let Some(max_tokens) = options.max_output_tokens.or(config.max_output_tokens) {
        body["max_tokens"] = json!(max_tokens);
    }
    if let Some(temperature) = options.temperature.or(config.temperature) {
        body["temperature"] = json!(temperature);
    }
    let reasoning_level = if config.thinking_supported {
        options.reasoning_level.as_str()
    } else {
        "off"
    };
    apply_request_profile(
        &mut body,
        profile,
        &config.provider_extra,
        &config.model_extra,
        reasoning_level,
        options
            .thinking_budget
            .or(config.thinking_budget)
            .unwrap_or(10_000),
    );
    body
}

fn openai_message(message: &Message, model: &str, profile_id: &str) -> Value {
    let mut value = match message {
        Message::System { content } => json!({"role":"system","content":content}),
        Message::User { content } => json!({"role":"user","content":content}),
        Message::UserMultimodal { content, images } => {
            let mut parts = Vec::with_capacity(images.len() + usize::from(!content.is_empty()));
            if !content.is_empty() {
                parts.push(json!({"type":"text","text":content}));
            }
            parts.extend(images.iter().map(|image| {
                json!({
                    "type":"image_url",
                    "image_url":{"url":openai_image_data_url(image),"detail":"auto"},
                })
            }));
            json!({"role":"user","content":parts})
        }
        Message::Assistant {
            content,
            provider_state: _,
        } => json!({"role":"assistant","content":content}),
        Message::AssistantToolCalls {
            content,
            calls,
            provider_state: _,
        } => json!({
            "role":"assistant",
            // A tool-call response may also carry narration; providers expect
            // it on the same assistant message as the calls.
            "content": if content.is_empty() { Value::Null } else { Value::String(content.clone()) },
            "tool_calls": calls.iter().map(|call| json!({
                "id":call.id, "type":"function",
                "function":{"name":call.name,"arguments":serde_json::to_string(&call.arguments).unwrap_or_else(|_| "{}".into())}
            })).collect::<Vec<_>>()
        }),
        Message::Tool {
            tool_call_id,
            content,
            ..
        } => json!({"role":"tool","tool_call_id":tool_call_id,"content":content}),
    };
    match message {
        Message::Assistant { provider_state, .. }
        | Message::AssistantToolCalls { provider_state, .. } => {
            restore_openai_provider_state(&mut value, provider_state, model, profile_id)
        }
        _ => {}
    }
    value
}

fn responses_body(
    config: &ProviderConfig,
    profile: &Value,
    messages: &[Message],
    tools: &[ToolDefinition],
    options: &TurnOptions,
) -> Value {
    let mut input = Vec::new();
    for message in messages {
        match message {
            Message::System { content } => input.push(json!({
                "type":"message",
                "role":"developer",
                "content":[{"type":"input_text","text":content}],
            })),
            Message::User { content } => input.push(json!({
                "type":"message",
                "role":"user",
                "content":[{"type":"input_text","text":content}],
            })),
            Message::UserMultimodal { content, images } => {
                let mut parts = Vec::with_capacity(images.len() + usize::from(!content.is_empty()));
                if !content.is_empty() {
                    parts.push(json!({"type":"input_text","text":content}));
                }
                parts.extend(images.iter().map(|image| {
                    json!({
                        "type":"input_image",
                        "image_url":openai_image_data_url(image),
                        "detail":"auto",
                    })
                }));
                input.push(json!({"type":"message","role":"user","content":parts}));
            }
            Message::Assistant {
                content,
                provider_state,
            } => {
                if let Some(output) = restored_responses_output(
                    provider_state,
                    &config.api_model_id,
                    profile_id(profile),
                ) {
                    input.extend(output);
                } else if !content.is_empty() {
                    input.push(json!({
                        "type":"message",
                        "role":"assistant",
                        "content":[{"type":"input_text","text":content}],
                    }));
                }
            }
            Message::AssistantToolCalls {
                content,
                calls,
                provider_state,
            } => {
                if let Some(output) = restored_responses_output(
                    provider_state,
                    &config.api_model_id,
                    profile_id(profile),
                ) {
                    input.extend(output);
                } else {
                    if !content.is_empty() {
                        input.push(json!({
                            "type":"message",
                            "role":"assistant",
                            "content":[{"type":"input_text","text":content}],
                        }));
                    }
                    input.extend(calls.iter().map(|call| {
                        json!({
                            "type":"function_call",
                            "call_id":call.id,
                            "name":call.name,
                            "arguments":serde_json::to_string(&call.arguments)
                                .unwrap_or_else(|_| "{}".into()),
                        })
                    }));
                }
            }
            Message::Tool {
                tool_call_id,
                content,
                ..
            } => input.push(json!({
                "type":"function_call_output",
                "call_id":tool_call_id,
                "output":content,
            })),
        }
    }

    let mut body = json!({
        "model":config.api_model_id,
        "input":input,
        "stream":false,
    });
    if !tools.is_empty() {
        body["tools"] = Value::Array(
            tools
                .iter()
                .map(|tool| {
                    json!({
                        "type":"function",
                        "name":tool.name,
                        "description":tool.description,
                        "parameters":tool.input_schema,
                    })
                })
                .collect(),
        );
        body["tool_choice"] = json!("auto");
    }
    if let Some(max_tokens) = options.max_output_tokens.or(config.max_output_tokens) {
        body["max_output_tokens"] = json!(max_tokens);
    }
    if let Some(temperature) = options.temperature.or(config.temperature) {
        body["temperature"] = json!(temperature);
    }
    apply_configured_reasoning(&mut body, config, profile, options);
    body
}

fn gemini_body(
    config: &ProviderConfig,
    profile: &Value,
    messages: &[Message],
    tools: &[ToolDefinition],
    options: &TurnOptions,
) -> Value {
    let mut system_parts = Vec::new();
    let mut contents = Vec::new();
    for message in messages {
        match message {
            Message::System { content } => system_parts.push(json!({"text":content})),
            Message::User { content } => contents.push(json!({
                "role":"user",
                "parts":[{"text":content}],
            })),
            Message::UserMultimodal { content, images } => {
                let mut parts = Vec::with_capacity(images.len() + usize::from(!content.is_empty()));
                if !content.is_empty() {
                    parts.push(json!({"text":content}));
                }
                parts.extend(images.iter().map(|image| {
                    json!({
                        "inline_data":{"mime_type":image.mime_type,"data":image.data_base64},
                    })
                }));
                contents.push(json!({"role":"user","parts":parts}));
            }
            Message::Assistant {
                content,
                provider_state,
            } => {
                if let Some(restored) = restored_gemini_content(
                    provider_state,
                    &config.api_model_id,
                    profile_id(profile),
                ) {
                    contents.push(restored);
                } else {
                    contents.push(json!({
                        "role":"model",
                        "parts":[{"text":content}],
                    }));
                }
            }
            Message::AssistantToolCalls {
                content,
                calls,
                provider_state,
            } => {
                if let Some(restored) = restored_gemini_content(
                    provider_state,
                    &config.api_model_id,
                    profile_id(profile),
                ) {
                    contents.push(restored);
                } else {
                    let mut parts = Vec::new();
                    if !content.is_empty() {
                        parts.push(json!({"text":content}));
                    }
                    parts.extend(calls.iter().map(|call| json!({
                        "functionCall":{
                            "name":call.name,
                            "args":call.arguments,
                        }
                    })));
                    contents.push(json!({"role":"model","parts":parts}));
                }
            }
            Message::Tool { name, content, .. } => {
                let parsed = serde_json::from_str::<Value>(content)
                    .unwrap_or_else(|_| json!({"result":content}));
                let response = if parsed.is_object() {
                    parsed
                } else {
                    json!({"result":parsed})
                };
                contents.push(json!({
                    "role":"user",
                    "parts":[{"functionResponse":{
                        "name":if name.is_empty() { "tool" } else { name },
                        "response":response,
                    }}],
                }));
            }
        }
    }

    let mut body = json!({"contents":contents});
    if !system_parts.is_empty() {
        body["systemInstruction"] = json!({"parts":system_parts});
    }
    let mut generation_config = Map::new();
    if let Some(max_tokens) = options.max_output_tokens.or(config.max_output_tokens) {
        generation_config.insert("maxOutputTokens".into(), json!(max_tokens));
    }
    if let Some(temperature) = options.temperature.or(config.temperature) {
        generation_config.insert("temperature".into(), json!(temperature));
    }
    if !generation_config.is_empty() {
        body["generationConfig"] = Value::Object(generation_config);
    }
    if !tools.is_empty() {
        body["tools"] = json!([{
            "functionDeclarations":tools.iter().map(|tool| json!({
                "name":tool.name,
                "description":tool.description,
                "parameters":tool.input_schema,
            })).collect::<Vec<_>>()
        }]);
        body["toolConfig"] = json!({"functionCallingConfig":{"mode":"AUTO"}});
    }
    apply_configured_reasoning(&mut body, config, profile, options);
    body
}

fn apply_configured_reasoning(
    body: &mut Value,
    config: &ProviderConfig,
    profile: &Value,
    options: &TurnOptions,
) {
    let reasoning_level = if config.thinking_supported {
        options.reasoning_level.as_str()
    } else {
        "off"
    };
    apply_request_profile(
        body,
        profile,
        &config.provider_extra,
        &config.model_extra,
        reasoning_level,
        options
            .thinking_budget
            .or(config.thinking_budget)
            .unwrap_or(10_000),
    );
}

fn anthropic_body(
    config: &ProviderConfig,
    profile: &Value,
    messages: &[Message],
    tools: &[ToolDefinition],
    options: &TurnOptions,
) -> Value {
    let system = messages
        .iter()
        .find_map(|message| match message {
            Message::System { content } => Some(content.clone()),
            _ => None,
        })
        .unwrap_or_default();
    let mut converted = Vec::new();
    for message in messages {
        match message {
            Message::System { .. } => {}
            Message::User { content } => converted.push(json!({"role":"user","content":content})),
            Message::UserMultimodal { content, images } => {
                let mut blocks = Vec::with_capacity(images.len() + usize::from(!content.is_empty()));
                if !content.is_empty() {
                    blocks.push(json!({"type":"text","text":content}));
                }
                blocks.extend(images.iter().map(|image| json!({
                    "type":"image",
                    "source":{
                        "type":"base64",
                        "media_type":image.mime_type,
                        "data":image.data_base64,
                    },
                })));
                converted.push(json!({"role":"user","content":blocks}));
            }
            Message::Assistant {
                content,
                provider_state,
            } => {
                let mut blocks = restored_anthropic_blocks(
                    provider_state,
                    &config.api_model_id,
                    profile_id(profile),
                );
                blocks.push(json!({"type":"text","text":content}));
                converted.push(json!({"role":"assistant","content":blocks}));
            }
            Message::AssistantToolCalls {
                content,
                calls,
                provider_state,
            } => {
                let mut blocks = restored_anthropic_blocks(
                    provider_state,
                    &config.api_model_id,
                    profile_id(profile),
                );
                // Restored blocks already carry the original text when the raw
                // payload could be reused; only the reconstructed path needs it.
                let has_text = blocks
                    .iter()
                    .any(|block| block.get("type").and_then(Value::as_str) == Some("text"));
                if !content.is_empty() && !has_text {
                    blocks.push(json!({"type":"text","text":content}));
                }
                blocks.extend(calls.iter().map(|call| {
                    json!({"type":"tool_use","id":call.id,"name":call.name,"input":call.arguments})
                }));
                converted.push(json!({"role":"assistant","content":blocks}));
            }
            Message::Tool {
                tool_call_id,
                content,
                ..
            } => converted.push(json!({
                "role":"user", "content":[{"type":"tool_result","tool_use_id":tool_call_id,"content":content}]
            })),
        }
    }
    let mut body = json!({
        "model": config.api_model_id,
        "system": system,
        "messages": converted,
        "max_tokens": options.max_output_tokens.or(config.max_output_tokens).unwrap_or(4096),
    });
    if let Some(temperature) = options.temperature.or(config.temperature) {
        body["temperature"] = json!(temperature);
    }
    if !tools.is_empty() {
        body["tools"] = json!(tools
            .iter()
            .map(|tool| json!({
                "name":tool.name,"description":tool.description,"input_schema":tool.input_schema
            }))
            .collect::<Vec<_>>());
    }
    let reasoning_level = if config.thinking_supported {
        options.reasoning_level.as_str()
    } else {
        "off"
    };
    apply_request_profile(
        &mut body,
        profile,
        &config.provider_extra,
        &config.model_extra,
        reasoning_level,
        options
            .thinking_budget
            .or(config.thinking_budget)
            .unwrap_or(10_000),
    );
    enforce_anthropic_thinking_limits(&mut body);
    let request = profile.get("request").unwrap_or(&Value::Null);
    let thinking_active = body
        .pointer("/thinking/type")
        .and_then(Value::as_str)
        .is_some_and(|kind| !matches!(kind, "" | "disabled" | "none" | "off"));
    let omit_sampling = request
        .get("omit_sampling_always")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        || (thinking_active
            && request
                .get("omit_sampling_when_reasoning")
                .and_then(Value::as_bool)
                .unwrap_or(false));
    if omit_sampling {
        for field in ["temperature", "top_p", "top_k"] {
            body.as_object_mut().map(|object| object.remove(field));
        }
    }
    body
}

fn enforce_anthropic_thinking_limits(payload: &mut Value) {
    if payload.pointer("/thinking/type").and_then(Value::as_str) != Some("enabled") {
        return;
    }
    let budget = payload
        .pointer("/thinking/budget_tokens")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        .max(1_024);
    payload["thinking"]["budget_tokens"] = json!(budget);
    let max_tokens = payload
        .get("max_tokens")
        .and_then(Value::as_u64)
        .unwrap_or(0);
    if max_tokens <= budget {
        payload["max_tokens"] = json!(budget + 1);
    }
}

fn parse_openai(payload: Value, model: &str, profile_id: &str) -> Result<ModelTurn, RuntimeError> {
    if payload
        .pointer("/choices/0/finish_reason")
        .and_then(Value::as_str)
        == Some("length")
    {
        return Err(RuntimeError::Model(
            "provider reached max output tokens (finish_reason=length); incomplete answer or tool call discarded".into(),
        ));
    }
    let Some(message) = payload.pointer("/choices/0/message") else {
        return Ok(ModelTurn::Text {
            text: String::new(),
            reasoning: String::new(),
            provider_state: Value::Null,
        });
    };
    let provider_state = openai_provider_state(message, model, profile_id);
    // Read content before the tool-call branch: a response may carry both, and
    // the narration must survive into the runtime's history.
    let text = message
        .get("content")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let reasoning = message
        .get("reasoning_content")
        .or_else(|| message.get("reasoning"))
        .or_else(|| message.get("thinking"))
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_owned();
    if let Some(calls) = message.get("tool_calls").and_then(Value::as_array) {
        if !calls.is_empty() {
            return Ok(ModelTurn::ToolCalls {
                text: text.into(),
                calls: calls
                    .iter()
                    .map(|call| {
                        let raw = call
                            .pointer("/function/arguments")
                            .and_then(Value::as_str)
                            .unwrap_or("{}");
                        ToolCall {
                            id: call
                                .get("id")
                                .and_then(Value::as_str)
                                .unwrap_or_default()
                                .into(),
                            name: call
                                .pointer("/function/name")
                                .and_then(Value::as_str)
                                .unwrap_or_default()
                                .into(),
                            arguments: serde_json::from_str(raw).unwrap_or_else(|_| json!({})),
                        }
                    })
                    .collect(),
                provider_state,
            });
        }
    }
    Ok(ModelTurn::Text {
        text: text.into(),
        reasoning,
        provider_state,
    })
}

fn parse_anthropic(
    payload: Value,
    model: &str,
    profile_id: &str,
) -> Result<ModelTurn, RuntimeError> {
    let Some(content) = payload.get("content").and_then(Value::as_array) else {
        return Ok(ModelTurn::Text {
            text: String::new(),
            reasoning: String::new(),
            provider_state: Value::Null,
        });
    };
    let provider_state = anthropic_provider_state(content, model, profile_id);
    // Compute the narration before the tool-call branch so a response carrying
    // both a text block and tool_use does not lose the text.
    let text = content
        .iter()
        .filter(|item| item.get("type").and_then(Value::as_str) == Some("text"))
        .filter_map(|item| item.get("text").and_then(Value::as_str))
        .collect::<String>();
    let calls = content
        .iter()
        .filter(|item| item.get("type").and_then(Value::as_str) == Some("tool_use"))
        .map(|item| ToolCall {
            id: item
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .into(),
            name: item
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .into(),
            arguments: item.get("input").cloned().unwrap_or_else(|| json!({})),
        })
        .collect::<Vec<_>>();
    if !calls.is_empty() {
        return Ok(ModelTurn::ToolCalls {
            text,
            calls,
            provider_state,
        });
    }
    let reasoning = content
        .iter()
        .filter(|item| item.get("type").and_then(Value::as_str) == Some("thinking"))
        .filter_map(|item| item.get("thinking").and_then(Value::as_str))
        .collect::<String>();
    Ok(ModelTurn::Text {
        text,
        reasoning,
        provider_state,
    })
}

fn parse_responses(
    payload: Value,
    model: &str,
    profile_id: &str,
) -> Result<ModelTurn, RuntimeError> {
    let output = payload
        .get("output")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let provider_state = responses_provider_state(&output, model, profile_id);
    let mut calls = Vec::new();
    let mut text = String::new();
    let mut reasoning = String::new();
    for item in &output {
        match item.get("type").and_then(Value::as_str).unwrap_or("") {
            "function_call" => {
                let raw = item
                    .get("arguments")
                    .and_then(Value::as_str)
                    .unwrap_or("{}");
                calls.push(ToolCall {
                    id: item
                        .get("call_id")
                        .or_else(|| item.get("id"))
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_owned(),
                    name: item
                        .get("name")
                        .and_then(Value::as_str)
                        .unwrap_or_default()
                        .to_owned(),
                    arguments: serde_json::from_str(raw).unwrap_or_else(|_| json!({})),
                });
            }
            "message" => {
                if let Some(parts) = item.get("content").and_then(Value::as_array) {
                    for part in parts {
                        if matches!(
                            part.get("type").and_then(Value::as_str),
                            Some("output_text" | "text")
                        ) {
                            text.push_str(
                                part.get("text").and_then(Value::as_str).unwrap_or_default(),
                            );
                        }
                    }
                }
            }
            "reasoning" => {
                if let Some(summaries) = item.get("summary").and_then(Value::as_array) {
                    for summary in summaries {
                        reasoning.push_str(
                            summary
                                .get("text")
                                .and_then(Value::as_str)
                                .unwrap_or_default(),
                        );
                    }
                }
            }
            _ => {}
        }
    }
    if text.is_empty() {
        text = payload
            .get("output_text")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
    }
    if !calls.is_empty() {
        return Ok(ModelTurn::ToolCalls {
            text,
            calls,
            provider_state,
        });
    }
    Ok(ModelTurn::Text {
        text,
        reasoning,
        provider_state,
    })
}

fn parse_gemini(payload: Value, model: &str, profile_id: &str) -> Result<ModelTurn, RuntimeError> {
    let Some(candidates) = payload.get("candidates").and_then(Value::as_array) else {
        return Ok(ModelTurn::Text {
            text: String::new(),
            reasoning: String::new(),
            provider_state: Value::Null,
        });
    };
    let first_content = candidates
        .first()
        .and_then(|candidate| candidate.get("content"));
    let provider_state = first_content
        .map(|content| gemini_provider_state(content, model, profile_id))
        .unwrap_or(Value::Null);
    let mut calls = Vec::new();
    let mut text = String::new();
    let mut reasoning = String::new();
    for candidate in candidates {
        let Some(parts) = candidate
            .pointer("/content/parts")
            .and_then(Value::as_array)
        else {
            continue;
        };
        for part in parts {
            if let Some(call) = part.get("functionCall").and_then(Value::as_object) {
                let name = call.get("name").and_then(Value::as_str).unwrap_or_default();
                calls.push(ToolCall {
                    id: call
                        .get("id")
                        .and_then(Value::as_str)
                        .unwrap_or(name)
                        .to_owned(),
                    name: name.to_owned(),
                    arguments: call.get("args").cloned().unwrap_or_else(|| json!({})),
                });
                continue;
            }
            let part_text = part.get("text").and_then(Value::as_str).unwrap_or_default();
            if part.get("thought").and_then(Value::as_bool) == Some(true) {
                reasoning.push_str(part_text);
            } else {
                text.push_str(part_text);
            }
        }
    }
    if !calls.is_empty() {
        return Ok(ModelTurn::ToolCalls {
            text,
            calls,
            provider_state,
        });
    }
    Ok(ModelTurn::Text {
        text,
        reasoning,
        provider_state,
    })
}

fn openai_provider_state(message: &Value, model: &str, profile_id: &str) -> Value {
    let mut fields = Map::new();
    for key in ["reasoning_content", "thinking", "reasoning"] {
        if let Some(value) = message
            .get(key)
            .filter(|value| !value.is_null() && value.as_str() != Some(""))
        {
            fields.insert(key.to_owned(), value.clone());
        }
    }
    if fields.is_empty() {
        return Value::Null;
    }
    json!({
        "protocol":"openai-chat-completions",
        "profile_id":profile_id,
        "model":model,
        "message_fields":fields,
    })
}

fn restore_openai_provider_state(
    message: &mut Value,
    state: &Value,
    model: &str,
    profile_id: &str,
) {
    if !provider_state_matches(state, "openai-chat-completions", model, profile_id) {
        return;
    }
    if let Some(fields) = state.get("message_fields").and_then(Value::as_object) {
        for key in ["reasoning_content", "thinking", "reasoning"] {
            if let Some(value) = fields.get(key) {
                message[key] = value.clone();
            }
        }
    }
}

fn anthropic_provider_state(content: &[Value], model: &str, profile_id: &str) -> Value {
    let blocks = content
        .iter()
        .filter(|item| {
            matches!(
                item.get("type").and_then(Value::as_str),
                Some("thinking" | "redacted_thinking")
            )
        })
        .cloned()
        .collect::<Vec<_>>();
    if blocks.is_empty() {
        return Value::Null;
    }
    json!({
        "protocol":"anthropic-messages",
        "profile_id":profile_id,
        "model":model,
        "content_blocks":blocks
    })
}

fn restored_anthropic_blocks(state: &Value, model: &str, profile_id: &str) -> Vec<Value> {
    if !provider_state_matches(state, "anthropic-messages", model, profile_id) {
        return Vec::new();
    }
    state
        .get("content_blocks")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

fn responses_provider_state(output: &[Value], model: &str, profile_id: &str) -> Value {
    if !output.iter().any(|item| {
        matches!(
            item.get("type").and_then(Value::as_str),
            Some("reasoning" | "function_call")
        )
    }) {
        return Value::Null;
    }
    json!({
        "protocol":"openai-responses",
        "profile_id":profile_id,
        "model":model,
        "output":output
    })
}

fn restored_responses_output(state: &Value, model: &str, profile_id: &str) -> Option<Vec<Value>> {
    if !provider_state_matches(state, "openai-responses", model, profile_id) {
        return None;
    }
    state.get("output").and_then(Value::as_array).cloned()
}

fn gemini_provider_state(content: &Value, model: &str, profile_id: &str) -> Value {
    let continuation = content
        .get("parts")
        .and_then(Value::as_array)
        .is_some_and(|parts| {
            parts.iter().any(|part| {
                part.get("thought").and_then(Value::as_bool) == Some(true)
                    || part.get("thoughtSignature").is_some()
                    || part.get("functionCall").is_some_and(Value::is_object)
            })
        });
    if !continuation {
        return Value::Null;
    }
    json!({
        "protocol":"gemini-generative-language",
        "profile_id":profile_id,
        "model":model,
        "content":content,
    })
}

fn restored_gemini_content(state: &Value, model: &str, profile_id: &str) -> Option<Value> {
    if !provider_state_matches(state, "gemini-generative-language", model, profile_id) {
        return None;
    }
    state
        .get("content")
        .filter(|value| value.is_object())
        .cloned()
}

fn provider_state_matches(state: &Value, protocol: &str, model: &str, profile_id: &str) -> bool {
    state
        .get("protocol")
        .and_then(Value::as_str)
        .is_some_and(|value| value.trim().eq_ignore_ascii_case(protocol))
        && state
            .get("profile_id")
            .and_then(Value::as_str)
            .is_some_and(|value| value.trim() == profile_id.trim())
        && state
            .get("model")
            .and_then(Value::as_str)
            .is_some_and(|value| value.trim() == model.trim())
}

fn profile_protocol(profile: &Value) -> &str {
    profile
        .get("protocol")
        .and_then(Value::as_str)
        .unwrap_or("")
}

fn profile_id(profile: &Value) -> &str {
    profile.get("id").and_then(Value::as_str).unwrap_or("")
}

fn retryable_status(status: reqwest::StatusCode) -> bool {
    status.is_server_error() || matches!(status.as_u16(), 408 | 409 | 425 | 429)
}

fn provider_protocol(config: &ProviderConfig, profile: &Value) -> ProviderProtocol {
    match profile_protocol(profile) {
        "anthropic-messages" => ProviderProtocol::AnthropicMessages,
        "openai-responses" | "responses" => ProviderProtocol::OpenAiResponses,
        "gemini" | "gemini-generative-language" => ProviderProtocol::GeminiGenerativeLanguage,
        _ if config
            .api_type
            .trim()
            .to_ascii_lowercase()
            .contains("anthropic") =>
        {
            ProviderProtocol::AnthropicMessages
        }
        _ => ProviderProtocol::OpenAiChat,
    }
}

fn join_endpoint(base_url: &str, endpoint: &str) -> String {
    let base = base_url.trim_end_matches('/');
    let endpoint = if base.ends_with("/v1") && endpoint.starts_with("/v1/") {
        &endpoint[3..]
    } else {
        endpoint
    };
    format!("{base}/{}", endpoint.trim_start_matches('/'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn model_notes_enter_system_context_once_without_mutating_history() {
        let original = vec![
            Message::System {
                content: "Base instructions".into(),
            },
            Message::User {
                content: "hi".into(),
            },
        ];
        let with_notes = messages_with_model_notes(&original, "  Prefer concise answers.  ");
        assert_eq!(
            original[0],
            Message::System {
                content: "Base instructions".into()
            }
        );
        assert_eq!(
            with_notes[0],
            Message::System {
                content: "Base instructions\nCurrent model notes: Prefer concise answers.".into()
            }
        );
        assert_eq!(
            messages_with_model_notes(&with_notes, "Prefer concise answers."),
            with_notes
        );
        let inserted = messages_with_model_notes(&original[1..], "Use tools when needed");
        assert_eq!(
            inserted[0],
            Message::System {
                content: "Current model notes: Use tools when needed".into()
            }
        );
        let mut settings = config("model", Value::Null);
        settings.notes = "Prefer concise answers.".into();
        let profile = resolve_profile(
            &settings.api_type,
            &settings.base_url,
            &settings.api_model_id,
            &settings.provider_name,
            &settings.provider_extra,
            &settings.model_extra,
        );
        let body = openai_body(
            &settings,
            &profile,
            &with_notes,
            &[],
            &TurnOptions::default(),
        );
        assert_eq!(
            body.pointer("/messages/0/content"),
            Some(&json!(
                "Base instructions\nCurrent model notes: Prefer concise answers."
            ))
        );
    }

    fn native_test_policy() -> RetryPolicy {
        RetryPolicy {
            attempts: 1,
            timeout: Duration::from_secs(5),
            delays: vec![0.0],
            jitter: false,
            empty_response_retries: 0,
            stream_idle_timeout: Some(Duration::from_secs(1)),
        }
    }

    fn sse_server(frames: &str) -> (String, std::thread::JoinHandle<String>) {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let frames = frames.to_owned();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket
                .set_read_timeout(Some(Duration::from_secs(5)))
                .unwrap();
            let mut request = Vec::new();
            let mut buffer = [0u8; 4096];
            loop {
                let size = socket.read(&mut buffer).unwrap();
                if size == 0 {
                    break;
                }
                request.extend_from_slice(&buffer[..size]);
                if let Some(end) = request.windows(4).position(|part| part == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&request[..end]);
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            line.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .and_then(|part| part.trim().parse::<usize>().ok())
                        })
                        .unwrap_or(0);
                    if request.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n").unwrap();
            for piece in frames.as_bytes().chunks(7) {
                socket.write_all(piece).unwrap();
            }
            String::from_utf8(request).unwrap()
        });
        (format!("http://{address}"), server)
    }

    fn native_config(base_url: String, protocol: &str) -> ProviderConfig {
        let mut settings = config("native-model", Value::Null);
        settings.base_url = base_url;
        settings.provider_extra = json!({"adapter_profile_id":protocol});
        settings.api_type = match protocol {
            "anthropic-messages" => "anthropic",
            "gemini" => "gemini",
            _ => "openai-responses",
        }
        .into();
        settings
    }

    #[tokio::test]
    async fn anthropic_sse_emits_deltas_and_assembles_thinking_and_tool_input() {
        let frames = [
            "event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"model\":\"claude-remote\"}}\n\n",
            "event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"thinking\",\"thinking\":\"\"}}\n\n",
            "data: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"thinking_delta\",\"thinking\":\"plan\"}}\n\n",
            "data: {\"type\":\"content_block_stop\",\"index\":0}\n\n",
            "data: {\"type\":\"content_block_start\",\"index\":1,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\n",
            "data: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"text_delta\",\"text\":\"hello\"}}\n\n",
            "data: {\"type\":\"content_block_stop\",\"index\":1}\n\n",
            "data: {\"type\":\"content_block_start\",\"index\":2,\"content_block\":{\"type\":\"tool_use\",\"id\":\"call-1\",\"name\":\"lookup\",\"input\":{}}}\n\n",
            "data: {\"type\":\"content_block_delta\",\"index\":2,\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\"{\\\"x\\\":1}\"}}\n\n",
            "data: {\"type\":\"content_block_stop\",\"index\":2}\n\n",
            "data: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"tool_use\"}}\n\n",
            "data: {\"type\":\"message_stop\"}\n\n",
        ].concat();
        let (base, server) = sse_server(&frames);
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let backend = HttpModelBackend::with_retry_policy(
            native_config(base, "anthropic-messages"),
            native_test_policy(),
        )
        .unwrap()
        .with_stream(move |kind, delta| sink.lock().unwrap().push((kind.into(), delta)));
        let turn = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap();
        let request = server.join().unwrap();
        assert!(request.contains("/messages"));
        assert!(request.contains("\"stream\":true"));
        match turn {
            ModelTurn::ToolCalls {
                text: _,
                calls,
                provider_state,
            } => {
                assert_eq!(calls[0].arguments, json!({"x":1}));
                assert_eq!(provider_state["content_blocks"][0]["thinking"], "plan");
            }
            other => panic!("expected Anthropic tool call: {other:?}"),
        }
        assert!(events
            .lock()
            .unwrap()
            .contains(&("text_delta".into(), "hello".into())));
        assert!(events
            .lock()
            .unwrap()
            .contains(&("reasoning_delta".into(), "plan".into())));
    }

    #[tokio::test]
    async fn responses_sse_uses_native_items_and_completion() {
        let frames = [
            "data: {\"type\":\"response.created\",\"response\":{\"model\":\"gpt-remote\"}}\n\n",
            "data: {\"type\":\"response.output_item.added\",\"output_index\":0,\"item\":{\"type\":\"reasoning\",\"summary\":[]}}\n\n",
            "data: {\"type\":\"response.reasoning_summary_text.delta\",\"output_index\":0,\"summary_index\":0,\"delta\":\"plan\"}\n\n",
            "data: {\"type\":\"response.output_item.added\",\"output_index\":1,\"item\":{\"type\":\"message\",\"role\":\"assistant\",\"content\":[]}}\n\n",
            "data: {\"type\":\"response.output_text.delta\",\"output_index\":1,\"content_index\":0,\"delta\":\"hello\"}\n\n",
            "data: {\"type\":\"response.output_item.added\",\"output_index\":2,\"item\":{\"type\":\"function_call\",\"call_id\":\"call-1\",\"name\":\"lookup\",\"arguments\":\"\"}}\n\n",
            "data: {\"type\":\"response.function_call_arguments.delta\",\"output_index\":2,\"delta\":\"{\\\"x\\\":1}\"}\n\n",
            "data: {\"type\":\"response.completed\",\"response\":{\"status\":\"completed\",\"model\":\"gpt-remote\",\"output\":[{\"type\":\"reasoning\",\"summary\":[{\"type\":\"summary_text\",\"text\":\"plan\"}]},{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"hello\"}]},{\"type\":\"function_call\",\"call_id\":\"call-1\",\"name\":\"lookup\",\"arguments\":\"{\\\"x\\\":1}\"}]}}\n\n",
        ].concat();
        let (base, server) = sse_server(&frames);
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let backend = HttpModelBackend::with_retry_policy(
            native_config(base, "openai-responses"),
            native_test_policy(),
        )
        .unwrap()
        .with_stream(move |kind, delta| sink.lock().unwrap().push((kind.into(), delta)));
        let turn = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap();
        let request = server.join().unwrap();
        assert!(request.contains("/responses"));
        assert!(request.contains("\"stream\":true"));
        match turn {
            ModelTurn::ToolCalls {
                text: _,
                calls,
                provider_state,
            } => {
                assert_eq!(calls[0].arguments, json!({"x":1}));
                assert_eq!(provider_state["output"][0]["summary"][0]["text"], "plan");
            }
            other => panic!("expected Responses tool call: {other:?}"),
        }
        assert!(events
            .lock()
            .unwrap()
            .contains(&("text_delta".into(), "hello".into())));
        assert!(events
            .lock()
            .unwrap()
            .contains(&("reasoning_delta".into(), "plan".into())));
    }

    #[tokio::test]
    async fn gemini_sse_uses_stream_endpoint_and_preserves_thought_signature() {
        let frames = [
            "data: {\"modelVersion\":\"gemini-remote\",\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"plan\",\"thought\":true,\"thoughtSignature\":\"sig\"}]}}]}\n\n",
            "data: {\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"hello\"},{\"functionCall\":{\"name\":\"lookup\",\"args\":{\"x\":1}}}]}}]}\n\n",
            "data: {\"candidates\":[{\"finishReason\":\"STOP\"}]}\n\n",
        ].concat();
        let (base, server) = sse_server(&frames);
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let backend = HttpModelBackend::with_retry_policy(
            native_config(base, "gemini"),
            native_test_policy(),
        )
        .unwrap()
        .with_stream(move |kind, delta| sink.lock().unwrap().push((kind.into(), delta)));
        let turn = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap();
        let request = server.join().unwrap();
        assert!(request.contains(":streamGenerateContent?alt=sse"));
        assert!(!request.contains("\"stream\":true"));
        match turn {
            ModelTurn::ToolCalls {
                text: _,
                calls,
                provider_state,
            } => {
                assert_eq!(calls[0].arguments, json!({"x":1}));
                assert_eq!(
                    provider_state["content"]["parts"][0]["thoughtSignature"],
                    "sig"
                );
            }
            other => panic!("expected Gemini tool call: {other:?}"),
        }
        assert!(events
            .lock()
            .unwrap()
            .contains(&("text_delta".into(), "hello".into())));
        assert!(events
            .lock()
            .unwrap()
            .contains(&("reasoning_delta".into(), "plan".into())));
    }

    #[test]
    fn retry_policy_reads_host_config_with_safe_defaults() {
        let policy = RetryPolicy::from_config(&json!({
            "model_retries": 4,
            "model_timeout_seconds": 12.5,
            "model_stream_idle_timeout_seconds": null,
            "retry_delays_seconds": [0.25, -1, "bad", 3],
            "empty_response_retries": 2,
            "jitter": false,
        }));
        assert_eq!(policy.attempts, 4);
        assert_eq!(policy.timeout, Duration::from_millis(12_500));
        assert_eq!(policy.stream_idle_timeout, None);
        assert_eq!(policy.delays, vec![0.25, 3.0]);
        assert_eq!(policy.empty_response_retries, 2);
        assert!(!policy.jitter);
        assert_eq!(
            RetryPolicy::from_config(&json!({"model_timeout_seconds":-1})).stream_idle_timeout,
            Some(Duration::from_secs(120))
        );
    }

    #[test]
    fn native_stream_rejects_truncated_terminal_states() {
        let mut anthropic = NativeStream::new(ProviderProtocol::AnthropicMessages);
        anthropic
            .ingest(
                &json!({"type":"message_delta","delta":{"stop_reason":"max_tokens"}}),
                "",
                None,
                None,
            )
            .unwrap();
        anthropic
            .ingest(&json!({"type":"message_stop"}), "", None, None)
            .unwrap();
        assert!(anthropic.finish().unwrap_err().contains("truncated"));
        let mut unfinished = NativeStream::new(ProviderProtocol::AnthropicMessages);
        unfinished.ingest(&json!({"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"c","name":"lookup","input":{}}}), "", None, None).unwrap();
        unfinished
            .ingest(
                &json!({"type":"message_delta","delta":{"stop_reason":"tool_use"}}),
                "",
                None,
                None,
            )
            .unwrap();
        unfinished
            .ingest(&json!({"type":"message_stop"}), "", None, None)
            .unwrap();
        assert!(unfinished.finish().unwrap_err().contains("unfinished"));
        let mut responses = NativeStream::new(ProviderProtocol::OpenAiResponses);
        assert!(responses
            .ingest(&json!({"type":"response.incomplete"}), "", None, None)
            .is_err());
        let mut malformed_tool = NativeStream::new(ProviderProtocol::OpenAiResponses);
        malformed_tool.ingest(&json!({"type":"response.completed","response":{"status":"completed","output":[{"type":"function_call","call_id":"c","name":"lookup","arguments":"{"}]}}), "", None, None).unwrap();
        assert!(malformed_tool.finish().unwrap_err().contains("arguments"));
        let mut gemini = NativeStream::new(ProviderProtocol::GeminiGenerativeLanguage);
        gemini
            .ingest(
                &json!({"candidates":[{"finishReason":"MAX_TOKENS"}]}),
                "",
                None,
                None,
            )
            .unwrap();
        assert!(gemini.finish().unwrap_err().contains("MAX_TOKENS"));
    }

    #[tokio::test]
    async fn native_stream_idle_timeout_resets_provisional_output() {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 8192];
            let _ = socket.read(&mut buffer);
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"partial\"}}\n\n").unwrap();
            std::thread::sleep(Duration::from_millis(400));
        });
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let mut policy = native_test_policy();
        policy.stream_idle_timeout = Some(Duration::from_millis(100));
        let backend = HttpModelBackend::with_retry_policy(
            native_config(format!("http://{address}"), "anthropic-messages"),
            policy,
        )
        .unwrap()
        .with_stream(move |kind, delta| sink.lock().unwrap().push((kind.into(), delta)));
        let error = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap_err();
        server.join().unwrap();
        assert!(error.to_string().contains("idle timeout"));
        let events = events.lock().unwrap();
        assert!(events.contains(&("text_delta".into(), "partial".into())));
        assert_eq!(events.last(), Some(&("reset".into(), String::new())));
    }

    #[tokio::test]
    async fn native_sse_clean_eof_before_terminal_is_not_a_success() {
        let (base, server) = sse_server("data: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\",\"text\":\"\"}}\n\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"partial\"}}\n\n");
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let backend = HttpModelBackend::with_retry_policy(
            native_config(base, "anthropic-messages"),
            native_test_policy(),
        )
        .unwrap()
        .with_stream(move |kind, delta| sink.lock().unwrap().push((kind.into(), delta)));
        let error = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap_err();
        server.join().unwrap();
        assert!(error.to_string().contains("terminal event"));
        let events = events.lock().unwrap();
        assert!(events.contains(&("text_delta".into(), "partial".into())));
        assert_eq!(events.last(), Some(&("reset".into(), String::new())));
    }

    #[test]
    fn sse_boundaries_accept_cr_lf_and_crlf_line_endings() {
        assert_eq!(sse_frame_boundary(b"data: one\r\rdata: two"), Some((9, 2)));
        assert_eq!(sse_frame_boundary(b"data: one\n\ndata: two"), Some((9, 2)));
        assert_eq!(
            sse_frame_boundary(b"data: one\r\n\r\ndata: two"),
            Some((9, 4))
        );
    }

    #[tokio::test]
    async fn openai_sse_assembles_split_utf8_and_tool_fragments() {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut request = [0u8; 8192];
            let size = socket.read(&mut request).unwrap();
            let sent = String::from_utf8_lossy(&request[..size]);
            assert!(sent.contains("/chat/completions"));
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n").unwrap();
            let chunks = [
                "data: {\"model\":\"remote-model\",\"choices\":[{\"delta\":{\"content\":\"你\",\"reasoning_content\":\"思\"}}]}\n\n",
                "data: {\"choices\":[{\"delta\":{\"content\":\"好\",\"reasoning_content\":\"考\",\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"test\",\"arguments\":\"{\\\"x\\\":\"}}]}}]}\n\n",
                "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"function\":{\"arguments\":\"1}\"}}]}}]}\n\n",
                "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"tool_calls\"}]}\n\n",
                "data: [DONE]\n\n",
            ].concat().into_bytes();
            for piece in chunks.chunks(3) {
                socket.write_all(piece).unwrap();
            }
        });
        let client = reqwest::Client::builder().no_proxy().build().unwrap();
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let callback: Arc<dyn Fn(&'static str, String) + Send + Sync> =
            Arc::new(move |kind, delta| {
                sink.lock().unwrap().push((kind.into(), delta));
            });
        let response = client
            .post(format!("http://{address}/chat/completions"))
            .send()
            .await
            .unwrap();
        let payload = read_openai_stream(response, Some(&callback), None)
            .await
            .unwrap();
        assert_eq!(
            payload.pointer("/choices/0/finish_reason"),
            Some(&json!("tool_calls"))
        );
        server.join().unwrap();
        let turn = parse_openai(payload, "configured-model", "openai-chat").unwrap();
        match turn {
            ModelTurn::ToolCalls {
                text,
                calls,
                provider_state,
            } => {
                // The streamed narration arrives with the tool calls; keeping it
                // is what lets the transcript retain what the model said.
                assert_eq!(text, "你好");
                assert_eq!(calls[0].id, "call_1");
                assert_eq!(calls[0].name, "test");
                assert_eq!(calls[0].arguments, json!({"x":1}));
                assert_eq!(
                    provider_state.pointer("/message_fields/reasoning_content"),
                    Some(&json!("思考"))
                );
            }
            other => panic!("expected tool calls, got {other:?}"),
        }
        let events = events.lock().unwrap();
        assert_eq!(
            events
                .iter()
                .filter(|(kind, _)| kind == "text_delta")
                .map(|(_, value)| value.as_str())
                .collect::<String>(),
            "你好"
        );
        assert_eq!(
            events
                .iter()
                .filter(|(kind, _)| kind == "reasoning_delta")
                .map(|(_, value)| value.as_str())
                .collect::<String>(),
            "思考"
        );
    }

    #[test]
    fn openai_json_length_rejects_partial_text_and_tool_calls() {
        let cases = [
            json!({"choices":[{"finish_reason":"length","message":{"content":"partial"}}]}),
            json!({"choices":[{"finish_reason":"length","message":{"tool_calls":[{"id":"call_1","function":{"name":"write_file","arguments":"{\"path\":\"partial"}}]}}]}),
        ];
        for payload in cases {
            let error = parse_openai(payload, "model", "openai-chat").unwrap_err();
            assert!(error.to_string().contains("finish_reason=length"));
        }
        assert!(matches!(
            parse_openai(
                json!({"choices":[{"finish_reason":"stop","message":{"content":"complete"}}]}),
                "model",
                "openai-chat"
            )
            .unwrap(),
            ModelTurn::Text { text, .. } if text == "complete"
        ));
    }

    #[tokio::test]
    async fn openai_sse_length_is_preserved_and_rejects_partial_tool_call() {
        use std::io::{Read, Write};

        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut request = [0u8; 8192];
            socket.read(&mut request).unwrap();
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\ndata: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"write_file\",\"arguments\":\"{\\\"path\\\":\\\"partial\"}}]},\"finish_reason\":\"length\"}]}\n\ndata: [DONE]\n\n").unwrap();
        });
        let response = reqwest::Client::builder()
            .no_proxy()
            .build()
            .unwrap()
            .post(format!("http://{address}/chat/completions"))
            .send()
            .await
            .unwrap();
        let payload = read_openai_stream(response, None, None).await.unwrap();
        server.join().unwrap();
        assert_eq!(
            payload.pointer("/choices/0/finish_reason"),
            Some(&json!("length"))
        );
        assert!(parse_openai(payload, "model", "openai-chat")
            .unwrap_err()
            .to_string()
            .contains("finish_reason=length"));
    }

    #[tokio::test]
    async fn openai_sse_length_clears_provisional_text_without_transport_retry() {
        use std::io::{Read, Write};

        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut request = [0u8; 8192];
            socket.read(&mut request).unwrap();
            let partial = "partial".repeat(40);
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n").unwrap();
            write!(socket, "data: {{\"choices\":[{{\"delta\":{{\"content\":\"{partial}\"}},\"finish_reason\":\"length\"}}]}}\n\ndata: [DONE]\n\n").unwrap();
        });
        let mut settings = config("model", json!({}));
        settings.base_url = format!("http://{address}/v1");
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let stages = Arc::new(std::sync::Mutex::new(Vec::new()));
        let stage_sink = stages.clone();
        let backend = HttpModelBackend::with_retry_policy(
            settings,
            RetryPolicy {
                attempts: 2,
                timeout: Duration::from_secs(5),
                delays: vec![0.0],
                jitter: false,
                empty_response_retries: 0,
                stream_idle_timeout: None,
            },
        )
        .unwrap()
        .with_progress(move |stage| stage_sink.lock().unwrap().push(stage))
        .with_stream(move |kind, delta| sink.lock().unwrap().push((kind.into(), delta)));
        let error = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap_err();
        server.join().unwrap();
        assert!(error.to_string().contains("finish_reason=length"));
        assert!(!stages.lock().unwrap().contains(&"http_retry_wait"));
        assert_eq!(
            events.lock().unwrap().as_slice(),
            &[
                ("text_delta".into(), "partial".repeat(40)),
                ("reset".into(), String::new()),
            ]
        );
    }

    #[tokio::test]
    async fn openai_sse_rejects_clean_eof_after_partial_text_or_tool_call() {
        use std::io::{Read, Write};

        let partial_streams = [
            "data: {\"choices\":[{\"delta\":{\"content\":\"unfinished answer\"}}]}\n\n",
            "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",\"function\":{\"name\":\"test\",\"arguments\":\"{\\\"x\\\":\"}}]}}]}\n\n",
        ];
        for partial in partial_streams {
            let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let address = listener.local_addr().unwrap();
            let server = std::thread::spawn(move || {
                let (mut socket, _) = listener.accept().unwrap();
                let mut request = [0u8; 8192];
                socket.read(&mut request).unwrap();
                socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n").unwrap();
                socket.write_all(partial.as_bytes()).unwrap();
            });
            let response = reqwest::Client::builder()
                .no_proxy()
                .build()
                .unwrap()
                .post(format!("http://{address}/chat/completions"))
                .send()
                .await
                .unwrap();
            let error = read_openai_stream(response, None, None).await.unwrap_err();
            server.join().unwrap();
            assert_eq!(error, "provider SSE ended before [DONE]");
        }
    }

    #[tokio::test]
    async fn streaming_retry_resets_provisional_output_and_keeps_final_authoritative() {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            for attempt in 0..2 {
                let (mut socket, _) = listener.accept().unwrap();
                let mut request = [0u8; 16384];
                let size = socket.read(&mut request).unwrap();
                let sent = String::from_utf8_lossy(&request[..size]);
                assert!(sent.contains("\"stream\":true"), "{sent}");
                if attempt == 0 {
                    let partial = "wrong".repeat(52);
                    socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n").unwrap();
                    write!(
                        socket,
                        "data: {{\"choices\":[{{\"delta\":{{\"content\":\"{partial}\"}}}}]}}\n\n"
                    )
                    .unwrap();
                } else {
                    socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\ndata: {\"model\":\"winner\",\"choices\":[{\"delta\":{\"content\":\"right\"}}]}\n\ndata: [DONE]\n\n").unwrap();
                }
            }
        });
        let mut settings = config("configured", json!({}));
        settings.base_url = format!("http://{address}/v1");
        settings.provider_extra =
            json!({"adapter_profile_id":"openai-chat", "request_body":{"stream":false}});
        let events = Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
        let sink = events.clone();
        let backend = HttpModelBackend::with_retry_policy(
            settings,
            RetryPolicy {
                attempts: 2,
                timeout: Duration::from_secs(5),
                delays: vec![0.0],
                jitter: false,
                empty_response_retries: 0,
                stream_idle_timeout: None,
            },
        )
        .unwrap()
        .with_stream(move |kind, delta| sink.lock().unwrap().push((kind.into(), delta)));
        let turn = backend
            .complete(
                "configured",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap();
        server.join().unwrap();
        assert!(matches!(turn, ModelTurn::Text { text, .. } if text == "right"));
        assert_eq!(backend.runtime_model_id("configured"), "winner");
        assert_eq!(
            events.lock().unwrap().as_slice(),
            &[
                ("text_delta".into(), "wrong".repeat(52)),
                ("reset".into(), "".into()),
                ("text_delta".into(), "right".into()),
            ]
        );
    }

    #[test]
    fn retry_waits_follow_the_shared_rhythm() {
        let policy = RetryPolicy {
            jitter: false,
            ..RetryPolicy::default()
        };
        assert_eq!(policy.attempts, 10);
        assert_eq!(policy.timeout, Duration::from_secs(360));
        assert_eq!(policy.empty_response_retries, 3);
        // 1, 1, 2, 5, 5, then the tail repeats.
        let waits: Vec<f64> = (0..7).map(|index| policy.delay_seconds(index)).collect();
        assert_eq!(waits, vec![1.0, 1.0, 2.0, 5.0, 5.0, 5.0, 5.0]);
    }

    #[test]
    fn jitter_only_spreads_the_wait() {
        let policy = RetryPolicy::default();
        for _ in 0..50 {
            let wait = policy.delay_seconds(3);
            assert!(
                (2.5..=7.5).contains(&wait),
                "jittered wait out of range: {wait}"
            );
        }
    }

    #[test]
    fn retryable_http_statuses_match_python_policy() {
        for status in [408, 409, 425, 429, 500, 502, 503, 504, 599] {
            assert!(
                retryable_status(reqwest::StatusCode::from_u16(status).unwrap()),
                "status {status} should be retried"
            );
        }
        for status in [400, 401, 403, 404, 422] {
            assert!(
                !retryable_status(reqwest::StatusCode::from_u16(status).unwrap()),
                "status {status} should be fatal"
            );
        }
    }

    #[test]
    fn connection_diagnostics_are_actionable_and_do_not_echo_error_sources() {
        let cases = [
            (
                io::Error::other("secret-token at https://private.example/path"),
                true,
                "provider DNS lookup failed before response headers (check network or DNS)",
            ),
            (
                io::Error::new(io::ErrorKind::ConnectionRefused, "private.example:443"),
                false,
                "provider TCP connection refused before response headers (check server or network)",
            ),
            (
                io::Error::new(io::ErrorKind::NetworkUnreachable, "private.example"),
                false,
                "provider network unreachable before response headers (check network access)",
            ),
            (
                io::Error::other("invalid peer certificate: UnknownIssuer"),
                false,
                "provider TLS certificate issuer is not trusted before response headers (check device trust store or network interception)",
            ),
            (
                io::Error::other("invalid peer certificate: Expired"),
                false,
                "provider TLS certificate expired before response headers (check device clock)",
            ),
            (
                io::Error::other("invalid peer certificate: NotValidYet"),
                false,
                "provider TLS certificate not yet valid before response headers (check device clock)",
            ),
            (
                io::Error::other("invalid peer certificate: NotValidForName"),
                false,
                "provider TLS certificate hostname mismatch before response headers (check provider URL or network interception)",
            ),
            (
                io::Error::other("invalid peer certificate: Revoked"),
                false,
                "provider TLS certificate revocation check failed before response headers",
            ),
            (
                io::Error::other("invalid peer certificate: BadEncoding"),
                false,
                "provider TLS certificate verification failed before response headers (check device clock and trusted certificates)",
            ),
            (
                io::Error::other("rustls handshake failure"),
                false,
                "provider TLS handshake failed before response headers (check network and TLS settings)",
            ),
            (
                io::Error::other("proxy tunnel refused: user:secret@private.example"),
                false,
                "provider proxy connection failed before response headers (check proxy settings)",
            ),
            (
                io::Error::other("secret-token at https://private.example/path"),
                false,
                "provider connection failed before response headers (DNS/TCP/TLS/proxy cause unknown)",
            ),
        ];
        for (error, dns, expected) in cases {
            let detail = connection_failure_detail(&error, dns);
            assert_eq!(detail, expected);
            assert!(!detail.contains("secret"));
            assert!(!detail.contains("private.example"));
        }
    }

    #[tokio::test]
    async fn a_stalled_provider_times_out_instead_of_hanging() {
        use std::io::Read;
        // Accept the connection and never answer, so the attempt can only end
        // by timeout. Without a client timeout this call would never return.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buffer = [0u8; 2048];
                let _ = stream.read(&mut buffer);
                std::thread::sleep(Duration::from_secs(30));
            }
        });

        let mut settings = config("model", json!({}));
        settings.base_url = format!("http://{address}/v1");
        settings.provider_extra = json!({"adapter_profile_id": "openai-chat"});
        let stages = Arc::new(std::sync::Mutex::new(Vec::new()));
        let reported_stages = stages.clone();
        let backend = HttpModelBackend::with_retry_policy(
            settings,
            RetryPolicy {
                attempts: 1,
                timeout: Duration::from_secs(1),
                delays: vec![0.0],
                jitter: false,
                empty_response_retries: 0,
                stream_idle_timeout: None,
            },
        )
        .unwrap()
        .with_progress(move |stage| reported_stages.lock().unwrap().push(stage));

        let started = std::time::Instant::now();
        let result = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await;
        let error = result.expect_err("a stalled provider must fail");
        assert!(error.to_string().contains("timed out"));
        assert_eq!(
            stages.lock().unwrap().as_slice(),
            [
                "http_send_start",
                "http_request_built",
                "http_send_timeout",
                "http_transport_error"
            ]
        );
        assert!(
            started.elapsed() < Duration::from_secs(10),
            "the attempt must be bounded, took {:?}",
            started.elapsed()
        );
    }

    #[tokio::test]
    async fn response_header_deadline_cancels_a_stalled_send() {
        use std::io::Read;

        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 1024];
            let _ = stream.read(&mut buffer);
            std::thread::sleep(Duration::from_millis(500));
        });
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(5))
            .build()
            .unwrap();
        let stages = Arc::new(std::sync::Mutex::new(vec!["http_request_built"]));
        let reported_stages = stages.clone();
        let started = std::time::Instant::now();
        let request = client
            .post(format!("http://{address}/test"))
            .body("hello")
            .build()
            .unwrap();
        let send = AbortSendOnDrop(tokio::spawn(async move { client.execute(request).await }));
        let result = send_until_headers_with_marker(
            send,
            Duration::from_millis(250),
            Duration::from_millis(20),
            move || {
                reported_stages
                    .lock()
                    .unwrap()
                    .push("http_waiting_for_headers")
            },
        )
        .await;
        assert!(matches!(result, Err(HeaderSendError::Timeout)));
        assert_eq!(
            stages.lock().unwrap().as_slice(),
            ["http_request_built", "http_waiting_for_headers"]
        );
        assert!(started.elapsed() < Duration::from_secs(1));
        server.join().unwrap();
    }

    #[tokio::test(flavor = "multi_thread", worker_threads = 2)]
    async fn header_watchdogs_survive_a_blocking_send_poll() {
        let (started_tx, started_rx) = tokio::sync::oneshot::channel();
        let send = AbortSendOnDrop(tokio::spawn(async {
            // Deliberately block one worker. The watchdog must run on another.
            let _ = started_tx.send(());
            std::thread::sleep(Duration::from_millis(300));
            std::future::pending::<Result<reqwest::Response, reqwest::Error>>().await
        }));
        started_rx.await.expect("the blocking send must start");
        let marked = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let on_waiting = marked.clone();
        let started = std::time::Instant::now();
        let result = send_until_headers_with_marker(
            send,
            Duration::from_millis(100),
            Duration::from_millis(20),
            move || on_waiting.store(true, std::sync::atomic::Ordering::SeqCst),
        )
        .await;
        assert!(matches!(result, Err(HeaderSendError::Timeout)));
        assert!(marked.load(std::sync::atomic::Ordering::SeqCst));
        assert!(started.elapsed() < Duration::from_millis(250));
    }

    #[tokio::test]
    async fn header_watchdogs_abort_a_pending_send() {
        let send = tokio::spawn(std::future::pending::<
            Result<reqwest::Response, reqwest::Error>,
        >());
        let abort_handle = send.abort_handle();
        let result = send_until_headers_with_marker(
            AbortSendOnDrop(send),
            Duration::from_millis(50),
            Duration::from_millis(10),
            || {},
        )
        .await;
        assert!(matches!(result, Err(HeaderSendError::Timeout)));
        tokio::time::timeout(Duration::from_secs(1), async {
            while !abort_handle.is_finished() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("a timed-out send task must be aborted");
    }

    #[tokio::test]
    async fn send_task_panic_is_classified_without_exposing_panic_payload() {
        let send = tokio::spawn(async {
            panic!("secret panic payload");
            #[allow(unreachable_code)]
            Ok::<reqwest::Response, reqwest::Error>(unreachable!())
        });
        let result = send_until_headers_with_marker(
            AbortSendOnDrop(send),
            Duration::from_secs(1),
            Duration::from_secs(1),
            || {},
        )
        .await;
        assert!(matches!(result, Err(HeaderSendError::TaskPanicked)));
    }

    #[tokio::test]
    async fn send_task_cancellation_is_classified() {
        let send = tokio::spawn(std::future::pending::<
            Result<reqwest::Response, reqwest::Error>,
        >());
        send.abort();
        let result = send_until_headers_with_marker(
            AbortSendOnDrop(send),
            Duration::from_secs(1),
            Duration::from_secs(1),
            || {},
        )
        .await;
        assert!(matches!(result, Err(HeaderSendError::TaskCancelled)));
    }

    #[tokio::test]
    async fn cancelling_header_wait_aborts_send() {
        let send = tokio::spawn(std::future::pending::<
            Result<reqwest::Response, reqwest::Error>,
        >());
        let abort_handle = send.abort_handle();
        let waiter = tokio::spawn(send_until_headers_with_marker(
            AbortSendOnDrop(send),
            Duration::from_secs(10),
            Duration::from_secs(5),
            || {},
        ));
        tokio::task::yield_now().await;
        waiter.abort();
        let _ = waiter.await;
        tokio::time::timeout(Duration::from_secs(1), async {
            while !abort_handle.is_finished() {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("cancelling the waiter must abort the send task");
    }

    #[tokio::test]
    async fn invalid_base_url_fails_request_build_without_sending_or_retrying() {
        let mut settings = config("model", json!({}));
        settings.base_url = "http://[secret-path".into();
        let stages = Arc::new(std::sync::Mutex::new(Vec::new()));
        let reported_stages = stages.clone();
        let backend = HttpModelBackend::with_retry_policy(
            settings,
            RetryPolicy {
                attempts: 10,
                timeout: Duration::from_secs(2),
                delays: vec![0.0],
                jitter: false,
                empty_response_retries: 0,
                stream_idle_timeout: None,
            },
        )
        .unwrap()
        .with_progress(move |stage| reported_stages.lock().unwrap().push(stage));
        let error = backend
            .complete(
                "model",
                &[Message::User {
                    content: "secret prompt".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap_err();
        assert_eq!(
            stages.lock().unwrap().as_slice(),
            ["http_send_start", "http_request_build_error"]
        );
        assert_eq!(
            error.to_string(),
            "model error: provider request could not be built"
        );
        assert!(!error.to_string().contains("secret"));
    }

    #[tokio::test]
    async fn preheader_failure_has_two_attempts_and_safe_stages() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        drop(listener);

        let mut settings = config("model", json!({}));
        settings.base_url = format!("http://{address}/secret-path");
        let stages = Arc::new(std::sync::Mutex::new(Vec::new()));
        let reported_stages = stages.clone();
        let mut backend = HttpModelBackend::with_retry_policy(
            settings,
            RetryPolicy {
                attempts: 10,
                timeout: Duration::from_secs(2),
                delays: vec![0.0],
                jitter: false,
                empty_response_retries: 0,
                stream_idle_timeout: None,
            },
        )
        .unwrap()
        .with_progress(move |stage| reported_stages.lock().unwrap().push(stage));
        // Keep the local failure independent of host proxy settings.
        backend.client = reqwest::Client::builder().no_proxy().build().unwrap();
        let error = backend
            .complete(
                "model",
                &[Message::User {
                    content: "secret prompt".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap_err();
        let stages = stages.lock().unwrap();
        assert_eq!(stages.len(), 9, "pre-header failures get only two attempts");
        assert_eq!(stages[0], "http_send_start");
        assert_eq!(stages[1], "http_request_built");
        assert!(matches!(
            stages[2],
            "http_send_timeout" | "http_connect_error"
        ));
        assert_eq!(stages[3], "http_transport_error");
        assert_eq!(stages[4], "http_retry_wait");
        assert_eq!(stages[5], "http_send_start");
        assert_eq!(stages[6], "http_request_built");
        assert!(matches!(
            stages[7],
            "http_send_timeout" | "http_connect_error"
        ));
        assert_eq!(stages[8], "http_transport_error");
        assert!(!error.to_string().contains("secret"));
    }

    #[tokio::test]
    async fn an_empty_completion_is_reprompted_and_exhaustion_is_visible() {
        use std::io::{Read, Write};

        async fn run_case(empty_retries: usize, final_text: Option<&str>) -> (usize, String) {
            let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            let address = listener.local_addr().unwrap();
            let final_text = final_text.map(str::to_owned);
            let server = std::thread::spawn(move || {
                let count = empty_retries + 1;
                listener.set_nonblocking(true).unwrap();
                let mut requests = Vec::new();
                for index in 0..count {
                    let deadline = std::time::Instant::now() + Duration::from_secs(5);
                    let mut stream = loop {
                        match listener.accept() {
                            Ok((stream, _)) => break stream,
                            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                                assert!(
                                    std::time::Instant::now() < deadline,
                                    "model retry request did not arrive"
                                );
                                std::thread::sleep(Duration::from_millis(10));
                            }
                            Err(error) => panic!("failed to accept retry request: {error}"),
                        }
                    };
                    stream.set_nonblocking(false).unwrap();
                    stream
                        .set_read_timeout(Some(Duration::from_secs(5)))
                        .unwrap();
                    let mut bytes = Vec::new();
                    let header_end;
                    loop {
                        let mut buffer = [0u8; 4096];
                        let size = stream.read(&mut buffer).unwrap();
                        assert!(size > 0);
                        bytes.extend_from_slice(&buffer[..size]);
                        if let Some(position) =
                            bytes.windows(4).position(|part| part == b"\r\n\r\n")
                        {
                            header_end = position + 4;
                            break;
                        }
                    }
                    let headers = String::from_utf8_lossy(&bytes[..header_end]);
                    let length = headers
                        .lines()
                        .find_map(|line| {
                            let (name, value) = line.split_once(':')?;
                            name.eq_ignore_ascii_case("content-length")
                                .then(|| value.trim().parse::<usize>().ok())
                                .flatten()
                        })
                        .unwrap();
                    while bytes.len() - header_end < length {
                        let mut buffer = [0u8; 4096];
                        let size = stream.read(&mut buffer).unwrap();
                        assert!(size > 0);
                        bytes.extend_from_slice(&buffer[..size]);
                    }
                    requests.push(
                        serde_json::from_slice::<Value>(&bytes[header_end..header_end + length])
                            .unwrap(),
                    );
                    let content = if index + 1 == count {
                        final_text.as_deref().unwrap_or("")
                    } else {
                        ""
                    };
                    let response = json!({"choices":[{"message":{"content":content}}]}).to_string();
                    write!(stream, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", response.len(), response).unwrap();
                }
                requests
            });
            let mut settings = config("model", json!({}));
            settings.base_url = format!("http://{address}/v1");
            settings.provider_extra = json!({"adapter_profile_id":"openai-chat"});
            let backend = HttpModelBackend::with_retry_policy(
                settings,
                RetryPolicy {
                    attempts: 1,
                    timeout: Duration::from_secs(5),
                    delays: vec![0.0],
                    jitter: false,
                    empty_response_retries: empty_retries,
                    stream_idle_timeout: None,
                },
            )
            .unwrap();
            let result = backend
                .complete(
                    "model",
                    &[Message::User {
                        content: "start".into(),
                    }],
                    &[],
                    &TurnOptions::default(),
                )
                .await;
            let requests = server.join().unwrap();
            for (index, request) in requests.iter().enumerate() {
                assert_eq!(request["messages"].as_array().unwrap().len(), 1 + index * 2);
                if index > 0 {
                    assert!(
                        request["messages"].as_array().unwrap().last().unwrap()["content"]
                            .as_str()
                            .unwrap()
                            .contains("no final text")
                    );
                }
            }
            let outcome = match result {
                Ok(ModelTurn::Text { text, .. }) => text,
                Err(error) => error.to_string(),
                _ => panic!("expected text or an exhausted empty response"),
            };
            (requests.len(), outcome)
        }

        let (count, text) = run_case(2, Some("answer")).await;
        assert_eq!(count, 3);
        assert_eq!(text, "answer");
        let (count, error) = run_case(2, None).await;
        assert_eq!(count, 3);
        assert!(error.contains("no content after 2 retries"));
    }

    #[tokio::test]
    async fn plain_text_client_error_is_fatal_without_retry() {
        use std::io::{Read, Write};

        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 4096];
            stream.read(&mut buffer).unwrap();
            write!(stream, "HTTP/1.1 401 Unauthorized\r\nContent-Type: text/plain\r\nContent-Length: 12\r\nConnection: close\r\n\r\nUnauthorized").unwrap();
        });
        let mut settings = config("model", json!({}));
        settings.base_url = format!("http://{address}/v1");
        let backend = HttpModelBackend::with_retry_policy(
            settings,
            RetryPolicy {
                attempts: 3,
                timeout: Duration::from_secs(2),
                delays: vec![0.0],
                jitter: false,
                empty_response_retries: 0,
                stream_idle_timeout: None,
            },
        )
        .unwrap();
        let error = backend
            .complete(
                "model",
                &[Message::User {
                    content: "hi".into(),
                }],
                &[],
                &TurnOptions::default(),
            )
            .await
            .unwrap_err();
        server.join().unwrap();
        assert!(error.to_string().contains("401 Unauthorized"));
    }

    #[test]
    fn native_protocols_expose_empty_completions_for_bounded_retry() {
        let turns = [
            parse_openai(
                json!({"choices":[{"message":{"content":""}}]}),
                "model",
                "openai-chat",
            ),
            parse_openai(json!({"choices":[]}), "model", "openai-chat"),
            parse_responses(json!({"output":[]}), "model", "openai-responses"),
            parse_anthropic(
                json!({"content":[{"type":"thinking","thinking":"plan"}]}),
                "model",
                "anthropic-messages",
            ),
            parse_anthropic(json!({}), "model", "anthropic-messages"),
            parse_gemini(
                json!({"candidates":[{"content":{"parts":[{"text":"plan","thought":true}]}}]}),
                "model",
                "gemini",
            ),
            parse_gemini(json!({}), "model", "gemini"),
        ];
        for turn in turns {
            assert!(matches!(turn.unwrap(), ModelTurn::Text { text, .. } if text.is_empty()));
        }
    }

    fn config(model: &str, model_extra: Value) -> ProviderConfig {
        ProviderConfig {
            api_type: "openai".into(),
            base_url: "https://example.invalid/v1".into(),
            api_key: "secret".into(),
            api_model_id: model.into(),
            max_output_tokens: Some(32_768),
            temperature: Some(0.7),
            provider_name: "Gateway".into(),
            provider_extra: json!({"adapter_profile_id":"openai-chat"}),
            model_extra,
            thinking_supported: true,
            thinking_budget: Some(10_000),
            notes: String::new(),
        }
    }

    #[test]
    fn image_messages_use_native_schemas_for_every_supported_protocol() {
        let message = Message::UserMultimodal {
            content: "What is shown?".into(),
            images: vec![ImageInput {
                attachment_id: "attachment-1".into(),
                mime_type: "image/png".into(),
                data_base64: "AAEC/w==".into(),
            }],
        };

        let chat_config = config("model", Value::Null);
        let chat_profile = resolve_profile(
            &chat_config.api_type,
            &chat_config.base_url,
            &chat_config.api_model_id,
            &chat_config.provider_name,
            &chat_config.provider_extra,
            &chat_config.model_extra,
        );
        let chat = openai_body(
            &chat_config,
            &chat_profile,
            std::slice::from_ref(&message),
            &[],
            &TurnOptions::default(),
        );
        assert_eq!(
            chat.pointer("/messages/0/content/1/image_url/url")
                .and_then(Value::as_str),
            Some("data:image/png;base64,AAEC/w==")
        );

        let mut responses_config = config("model", Value::Null);
        responses_config.api_type = "openai-responses".into();
        responses_config.provider_extra = json!({"adapter_profile_id":"openai-responses"});
        let responses_profile = resolve_profile(
            &responses_config.api_type,
            &responses_config.base_url,
            &responses_config.api_model_id,
            &responses_config.provider_name,
            &responses_config.provider_extra,
            &responses_config.model_extra,
        );
        let responses = responses_body(
            &responses_config,
            &responses_profile,
            std::slice::from_ref(&message),
            &[],
            &TurnOptions::default(),
        );
        assert_eq!(
            responses
                .pointer("/input/0/content/1/image_url")
                .and_then(Value::as_str),
            Some("data:image/png;base64,AAEC/w==")
        );

        let mut anthropic_config = config("model", Value::Null);
        anthropic_config.api_type = "anthropic".into();
        anthropic_config.provider_extra = json!({"adapter_profile_id":"anthropic-messages"});
        let anthropic_profile = resolve_profile(
            &anthropic_config.api_type,
            &anthropic_config.base_url,
            &anthropic_config.api_model_id,
            &anthropic_config.provider_name,
            &anthropic_config.provider_extra,
            &anthropic_config.model_extra,
        );
        let anthropic = anthropic_body(
            &anthropic_config,
            &anthropic_profile,
            std::slice::from_ref(&message),
            &[],
            &TurnOptions::default(),
        );
        assert_eq!(
            anthropic
                .pointer("/messages/0/content/1/source/media_type")
                .and_then(Value::as_str),
            Some("image/png")
        );
        assert_eq!(
            anthropic
                .pointer("/messages/0/content/1/source/data")
                .and_then(Value::as_str),
            Some("AAEC/w==")
        );

        let mut gemini_config = config("model", Value::Null);
        gemini_config.api_type = "gemini".into();
        gemini_config.provider_extra = json!({"adapter_profile_id":"gemini"});
        let gemini_profile = resolve_profile(
            &gemini_config.api_type,
            &gemini_config.base_url,
            &gemini_config.api_model_id,
            &gemini_config.provider_name,
            &gemini_config.provider_extra,
            &gemini_config.model_extra,
        );
        let gemini = gemini_body(
            &gemini_config,
            &gemini_profile,
            std::slice::from_ref(&message),
            &[],
            &TurnOptions::default(),
        );
        assert_eq!(
            gemini
                .pointer("/contents/0/parts/1/inline_data/mime_type")
                .and_then(Value::as_str),
            Some("image/png")
        );
        assert_eq!(
            gemini
                .pointer("/contents/0/parts/1/inline_data/data")
                .and_then(Value::as_str),
            Some("AAEC/w==")
        );
    }

    #[test]
    fn image_payloads_are_bounded_and_omitted_from_durable_history() {
        let message = Message::UserMultimodal {
            content: "Look".into(),
            images: vec![ImageInput {
                attachment_id: "attachment-1".into(),
                mime_type: "image/png".into(),
                data_base64: "AAEC/w==".into(),
            }],
        };
        validate_model_images(std::slice::from_ref(&message)).unwrap();
        let serialized = serde_json::to_value(&message).unwrap();
        assert_eq!(serialized["images"][0]["attachment_id"], "attachment-1");
        assert_eq!(serialized["images"][0]["mime_type"], "image/png");
        assert!(serialized["images"][0].get("data_base64").is_none());

        let too_large = "A".repeat(((MAX_MODEL_IMAGE_BYTES + 2) / 3) * 4 + 4);
        let oversized = Message::UserMultimodal {
            content: String::new(),
            images: vec![ImageInput {
                attachment_id: "attachment-2".into(),
                mime_type: "image/jpeg".into(),
                data_base64: too_large,
            }],
        };
        assert!(validate_model_images(&[oversized]).is_err());
        assert!(checked_base64_size("not base64!").is_none());
    }

    #[test]
    fn openai_body_uses_model_profile_reasoning_and_output_limit() {
        let config = config("deepseek-v4", json!({"adapter_profile_id":"deepseek-chat"}));
        let profile = resolve_profile(
            &config.api_type,
            &config.base_url,
            &config.api_model_id,
            &config.provider_name,
            &config.provider_extra,
            &config.model_extra,
        );
        let body = openai_body(
            &config,
            &profile,
            &[Message::User {
                content: "hi".into(),
            }],
            &[],
            &TurnOptions {
                reasoning_level: "max".into(),
                ..Default::default()
            },
        );
        assert_eq!(body["max_tokens"], 32_768);
        assert_eq!(
            body.pointer("/thinking/type"),
            Some(&Value::String("enabled".into()))
        );
        assert_eq!(body["reasoning_effort"], "max");
        assert!(body.get("tools").is_none());
    }

    #[test]
    fn provider_reasoning_state_is_replayed_only_for_the_same_model() {
        let state = json!({
            "protocol":"openai-chat-completions",
            "profile_id":"openai-chat",
            "model":"deepseek-v4",
            "message_fields":{"reasoning_content":"opaque","thinking":"opaque-thinking"}
        });
        let same = openai_message(
            &Message::Assistant {
                content: "answer".into(),
                provider_state: state.clone(),
            },
            "deepseek-v4",
            "openai-chat",
        );
        let changed = openai_message(
            &Message::Assistant {
                content: "answer".into(),
                provider_state: state,
            },
            "qwen3",
            "openai-chat",
        );
        assert_eq!(same["reasoning_content"], "opaque");
        assert_eq!(same["thinking"], "opaque-thinking");
        assert!(changed.get("reasoning_content").is_none());
        assert!(changed.get("thinking").is_none());

        let profile_changed = openai_message(
            &Message::Assistant {
                content: "answer".into(),
                provider_state: json!({
                    "protocol":"openai-chat-completions",
                    "profile_id":"deepseek-chat",
                    "model":"deepseek-v4",
                    "message_fields":{"reasoning_content":"opaque"}
                }),
            },
            "deepseek-v4",
            "openai-chat",
        );
        assert!(profile_changed.get("reasoning_content").is_none());
    }

    #[test]
    fn anthropic_manual_thinking_keeps_budget_below_output_limit() {
        let mut config = config(
            "claude-sonnet-4-5",
            json!({"adapter_profile_id":"anthropic-messages"}),
        );
        config.api_type = "anthropic".into();
        config.max_output_tokens = Some(4_096);
        let profile = resolve_profile(
            &config.api_type,
            &config.base_url,
            &config.api_model_id,
            &config.provider_name,
            &config.provider_extra,
            &config.model_extra,
        );
        let body = anthropic_body(
            &config,
            &profile,
            &[Message::User {
                content: "hi".into(),
            }],
            &[],
            &TurnOptions {
                reasoning_level: "max".into(),
                ..Default::default()
            },
        );
        assert_eq!(
            body.pointer("/thinking/budget_tokens"),
            Some(&json!(10_000))
        );
        assert_eq!(body["max_tokens"], 10_001);
        assert!(body.get("temperature").is_none());
    }

    #[test]
    fn responses_protocol_uses_native_input_tools_and_output_limit() {
        let mut config = config("gpt-5", Value::Null);
        config.api_type = "openai-responses".into();
        config.base_url = "https://api.openai.com/v1".into();
        config.provider_extra = json!({"adapter_profile_id":"openai-responses"});
        let profile = resolve_profile(
            &config.api_type,
            &config.base_url,
            &config.api_model_id,
            &config.provider_name,
            &config.provider_extra,
            &config.model_extra,
        );
        let body = responses_body(
            &config,
            &profile,
            &[
                Message::System {
                    content: "system".into(),
                },
                Message::User {
                    content: "hello".into(),
                },
                Message::AssistantToolCalls {
                    content: String::new(),
                    calls: vec![ToolCall {
                        id: "call-1".into(),
                        name: "read_text_file".into(),
                        arguments: json!({"path":"a.txt"}),
                    }],
                    provider_state: Value::Null,
                },
                Message::Tool {
                    tool_call_id: "call-1".into(),
                    name: "read_text_file".into(),
                    content: "ok".into(),
                },
            ],
            &[ToolDefinition {
                name: "read_text_file".into(),
                description: "Read".into(),
                input_schema: json!({"type":"object"}),
            }],
            &TurnOptions {
                reasoning_level: "xhigh".into(),
                ..Default::default()
            },
        );
        assert!(body.get("messages").is_none());
        assert!(body.get("max_tokens").is_none());
        assert_eq!(body["max_output_tokens"], 32_768);
        assert_eq!(body.pointer("/input/0/role"), Some(&json!("developer")));
        assert_eq!(body.pointer("/input/2/type"), Some(&json!("function_call")));
        assert_eq!(
            body.pointer("/input/3/type"),
            Some(&json!("function_call_output"))
        );
        assert_eq!(
            body.pointer("/tools/0/name"),
            Some(&json!("read_text_file"))
        );
        assert_eq!(body.pointer("/reasoning/effort"), Some(&json!("high")));

        let backend = HttpModelBackend::new(config).unwrap();
        assert_eq!(backend.request_url(), "https://api.openai.com/v1/responses");
    }

    #[test]
    fn responses_parser_preserves_reasoning_and_continuation_items() {
        let turn = parse_responses(
            json!({
                "model":"gpt-5-2026-01-01",
                "output":[
                    {"type":"reasoning","id":"r1","summary":[{"type":"summary_text","text":"plan"}]},
                    {"type":"message","role":"assistant","content":[{"type":"output_text","text":"answer"}]}
                ]
            }),
            "gpt-5",
            "openai-responses",
        )
        .unwrap();
        match turn {
            ModelTurn::Text {
                text,
                reasoning,
                provider_state,
            } => {
                assert_eq!(text, "answer");
                assert_eq!(reasoning, "plan");
                assert_eq!(provider_state["protocol"], "openai-responses");
                assert_eq!(provider_state["output"][0]["id"], "r1");
            }
            _ => panic!("expected a text response"),
        }
    }

    #[test]
    fn gemini_protocol_uses_native_envelope_and_preserves_thought_signature() {
        let mut config = config("gemini-2.5-pro", Value::Null);
        config.api_type = "gemini".into();
        config.base_url = "https://generativelanguage.googleapis.com".into();
        config.provider_extra = json!({"adapter_profile_id":"gemini"});
        let profile = resolve_profile(
            &config.api_type,
            &config.base_url,
            &config.api_model_id,
            &config.provider_name,
            &config.provider_extra,
            &config.model_extra,
        );
        let body = gemini_body(
            &config,
            &profile,
            &[
                Message::System {
                    content: "system".into(),
                },
                Message::User {
                    content: "hello".into(),
                },
            ],
            &[ToolDefinition {
                name: "write_text_file".into(),
                description: "Write".into(),
                input_schema: json!({"type":"object"}),
            }],
            &TurnOptions {
                reasoning_level: "medium".into(),
                ..Default::default()
            },
        );
        assert!(body.get("model").is_none());
        assert_eq!(
            body.pointer("/generationConfig/maxOutputTokens"),
            Some(&json!(32_768))
        );
        assert_eq!(
            body.pointer("/generationConfig/thinkingConfig/thinkingBudget"),
            Some(&json!(8_192))
        );
        assert_eq!(
            body.pointer("/tools/0/functionDeclarations/0/name"),
            Some(&json!("write_text_file"))
        );

        let turn = parse_gemini(
            json!({
                "modelVersion":"gemini-2.5-pro-001",
                "candidates":[{"content":{"role":"model","parts":[
                    {"text":"plan","thought":true,"thoughtSignature":"sig"},
                    {"text":"answer"}
                ]}}]
            }),
            "gemini-2.5-pro",
            "gemini",
        )
        .unwrap();
        match turn {
            ModelTurn::Text {
                text,
                reasoning,
                provider_state,
            } => {
                assert_eq!(text, "answer");
                assert_eq!(reasoning, "plan");
                assert_eq!(
                    provider_state["content"]["parts"][0]["thoughtSignature"],
                    "sig"
                );
            }
            _ => panic!("expected a text response"),
        }

        let backend = HttpModelBackend::new(config).unwrap();
        assert_eq!(
            backend.request_url(),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent"
        );
    }
}
