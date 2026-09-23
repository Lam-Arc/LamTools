use crate::profiles::{apply_request_profile, resolve_profile};
use crate::{
    Message, ModelBackend, ModelTurn, RuntimeError, ToolCall, ToolDefinition, TurnOptions,
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
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            attempts: 10,
            timeout: Duration::from_secs(360),
            delays: vec![1.0, 1.0, 2.0, 5.0, 5.0],
            jitter: true,
            empty_response_retries: 3,
        }
    }
}

impl RetryPolicy {
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
        join_endpoint(
            &self.config.base_url,
            &endpoint.replace("{model}", &self.config.api_model_id),
        )
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
        if status.is_success() && body.get("stream").and_then(Value::as_bool) == Some(true) {
            let payload =
                read_openai_stream(response, self.stream.as_ref(), self.progress.as_ref())
                    .await
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
    mut response: reqwest::Response,
    report: Option<&Arc<dyn Fn(&'static str, String) + Send + Sync>>,
    progress: Option<&Arc<dyn Fn(&'static str) + Send + Sync>>,
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
    while let Some(chunk) = response.chunk().await.map_err(|e| e.to_string())? {
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
        let mut request_messages = messages.to_vec();
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
            if protocol == ProviderProtocol::OpenAiChat && self.stream.is_some() {
                // Profiles can override body fields; force the requested wire protocol last.
                body["stream"] = Value::Bool(true);
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
                if protocol == ProviderProtocol::OpenAiChat {
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
        Message::Assistant {
            content,
            provider_state: _,
        } => json!({"role":"assistant","content":content}),
        Message::AssistantToolCalls {
            calls,
            provider_state: _,
        } => json!({
            "role":"assistant", "content": Value::Null,
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
                    contents.push(json!({
                        "role":"model",
                        "parts":calls.iter().map(|call| json!({
                            "functionCall":{
                                "name":call.name,
                                "args":call.arguments,
                            }
                        })).collect::<Vec<_>>(),
                    }));
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
                calls,
                provider_state,
            } => {
                let mut blocks = restored_anthropic_blocks(
                    provider_state,
                    &config.api_model_id,
                    profile_id(profile),
                );
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
    if let Some(calls) = message.get("tool_calls").and_then(Value::as_array) {
        if !calls.is_empty() {
            return Ok(ModelTurn::ToolCalls {
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
            calls,
            provider_state,
        });
    }
    let text = content
        .iter()
        .filter(|item| item.get("type").and_then(Value::as_str) == Some("text"))
        .filter_map(|item| item.get("text").and_then(Value::as_str))
        .collect::<String>();
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
    if !calls.is_empty() {
        return Ok(ModelTurn::ToolCalls {
            calls,
            provider_state,
        });
    }
    if text.is_empty() {
        text = payload
            .get("output_text")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
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
                calls,
                provider_state,
            } => {
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
        }
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
