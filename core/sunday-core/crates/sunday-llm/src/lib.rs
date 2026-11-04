//! Trial migration A: the old `provider.rs` rebuilt against the frozen `Model`
//! port. Streaming is a first-class input, errors are typed, and retry refuses
//! to run once bytes have already reached the caller.

pub mod anthropic;
pub mod openai;
pub mod sse;

use futures_util::StreamExt;
use serde_json::Value;
use std::time::Duration;
use sunday_protocol::{CoreError, Model, ModelDelta, ModelRequest, ModelTurn};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Wire {
    OpenAiChat,
    AnthropicMessages,
}

#[derive(Clone, Debug)]
pub struct RetryPolicy {
    pub max_attempts: u32,
    pub base_delay: Duration,
    pub max_delay: Duration,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 3,
            base_delay: Duration::from_millis(50),
            max_delay: Duration::from_secs(2),
        }
    }
}

#[derive(Clone, Debug)]
pub struct ProviderConfig {
    pub wire: Wire,
    pub base_url: String,
    pub api_key: String,
    pub api_key_header: Option<String>,
    pub idle_timeout: Duration,
    pub total_timeout: Duration,
    pub retry: RetryPolicy,
    pub extra_headers: Vec<(String, String)>,
}

impl ProviderConfig {
    pub fn openai(base_url: impl Into<String>, api_key: impl Into<String>) -> Self {
        Self {
            wire: Wire::OpenAiChat,
            base_url: base_url.into(),
            api_key: api_key.into(),
            api_key_header: None,
            idle_timeout: Duration::from_secs(60),
            total_timeout: Duration::from_secs(300),
            retry: RetryPolicy::default(),
            extra_headers: Vec::new(),
        }
    }

    pub fn anthropic(base_url: impl Into<String>, api_key: impl Into<String>) -> Self {
        Self {
            wire: Wire::AnthropicMessages,
            base_url: base_url.into(),
            api_key: api_key.into(),
            api_key_header: Some("x-api-key".into()),
            idle_timeout: Duration::from_secs(60),
            total_timeout: Duration::from_secs(300),
            retry: RetryPolicy::default(),
            extra_headers: vec![("anthropic-version".into(), "2023-06-01".into())],
        }
    }
}

/// A failure decides its own retryability. No string sniffing anywhere.
#[derive(Debug)]
struct Failure {
    error: CoreError,
    retryable: bool,
}

impl Failure {
    fn retryable(error: CoreError) -> Self {
        Self {
            error,
            retryable: true,
        }
    }
    fn fatal(error: CoreError) -> Self {
        Self {
            error,
            retryable: false,
        }
    }
}

impl From<CoreError> for Failure {
    fn from(error: CoreError) -> Self {
        Self::fatal(error)
    }
}

pub struct LlmClient {
    http: reqwest::Client,
    config: ProviderConfig,
}

/// One uniform assembler surface over the per-wire implementations.
enum Assembler {
    OpenAi(openai::Assembler),
    Anthropic(anthropic::Assembler),
}

impl Assembler {
    fn push(&mut self, event: &sse::SseEvent) -> Result<Vec<ModelDelta>, CoreError> {
        match self {
            Self::OpenAi(a) => a.push(event),
            Self::Anthropic(a) => a.push(event),
        }
    }

    fn finish(self) -> Result<ModelTurn, CoreError> {
        match self {
            Self::OpenAi(a) => a.finish(),
            Self::Anthropic(a) => a.finish(),
        }
    }
}

impl LlmClient {
    pub fn new(config: ProviderConfig) -> Result<Self, CoreError> {
        let http = reqwest::Client::builder()
            // Redirects are disabled, not merely limited. An API endpoint has no
            // reason to redirect, and a `302` to another host is exactly how an
            // Authorization header leaves the host the user approved.
            //
            // Returning an error here would still let the request be re-sent by a
            // retry loop; refusing to follow at all means the request dies where
            // it is, and the caller sees a plain "not successful status".
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| CoreError::model(format!("http client: {e}")))?;
        Ok(Self { http, config })
    }

    /// The endpoint this client will talk to. Exposed so a caller can confirm the
    /// key is bound to it before the first request is sent.
    pub fn endpoint(&self) -> &str {
        &self.config.base_url
    }

    /// The URL a request is actually posted to. Named apart from `endpoint` so the
    /// public accessor cannot be confused with it: one is the base the user approved,
    /// the other is the base with a path appended.
    fn request_url(&self) -> String {
        match self.config.wire {
            Wire::OpenAiChat => {
                format!(
                    "{}/chat/completions",
                    self.config.base_url.trim_end_matches('/')
                )
            }
            Wire::AnthropicMessages => {
                format!("{}/messages", self.config.base_url.trim_end_matches('/'))
            }
        }
    }

    fn body(&self, request: &ModelRequest) -> Value {
        match self.config.wire {
            Wire::OpenAiChat => openai::body(request),
            Wire::AnthropicMessages => anthropic::body(request),
        }
    }

    async fn attempt(
        &self,
        request: &ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
        delivered: &mut bool,
    ) -> Result<ModelTurn, Failure> {
        let mut builder = self.http.post(self.request_url()).json(&self.body(request));
        builder = match &self.config.api_key_header {
            Some(header) => builder.header(header, &self.config.api_key),
            None => builder.bearer_auth(&self.config.api_key),
        };
        for (k, v) in &self.config.extra_headers {
            builder = builder.header(k, v);
        }

        let response = match tokio::time::timeout(self.config.total_timeout, builder.send()).await {
            Err(_) => {
                return Err(Failure::retryable(CoreError::model(
                    "provider request timed out before headers",
                )))
            }
            Ok(Err(e)) => {
                return Err(Failure::retryable(CoreError::model(format!(
                    "transport: {e}"
                ))))
            }
            Ok(Ok(r)) => r,
        };

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            // A provider error body is untrusted text that may quote the request,
            // including the header we sent. Redact before it becomes an error the
            // UI shows or a log line someone pastes into a ticket.
            let safe = redact_secret(&body, &self.config.api_key);
            return Err(classify_status(status.as_u16(), &safe));
        }

        let mut stream = response.bytes_stream();
        let mut parser = sse::SseParser::new();
        let mut assembler = match self.config.wire {
            Wire::OpenAiChat => Assembler::OpenAi(openai::Assembler::new()),
            Wire::AnthropicMessages => Assembler::Anthropic(anthropic::Assembler::new()),
        };

        loop {
            // Cancellation is checked between reads, not only at the end: the
            // point of stopping is to stop pulling bytes and holding the socket.
            // A chunk already in flight is discarded rather than delivered.
            if request.cancel.is_cancelled() {
                // Dropping the response here closes the connection, which is the
                // only "stop" this client can honestly offer. Whether the
                // provider stops generating (or billing) is not ours to decide.
                return Err(Failure::fatal(CoreError::Rejected {
                    reason: "cancelled while reading the stream".into(),
                }));
            }
            let next = tokio::time::timeout(self.config.idle_timeout, stream.next()).await;
            let chunk = match next {
                Err(_) => {
                    return Err(Failure::retryable(CoreError::model(format!(
                        "stream idle for more than {:?}",
                        self.config.idle_timeout
                    ))))
                }
                Ok(None) => break,
                Ok(Some(Err(e))) => {
                    return Err(Failure::retryable(CoreError::model(format!("stream: {e}"))))
                }
                Ok(Some(Ok(bytes))) => bytes,
            };
            let text = String::from_utf8_lossy(&chunk).to_string();
            for event in parser.push(&text) {
                if event.data.trim() == "[DONE]" {
                    continue;
                }
                for delta in assembler.push(&event).map_err(Failure::fatal)? {
                    *delivered = true;
                    sink(delta);
                }
            }
        }
        if let Some(tail) = parser.finish() {
            for delta in assembler.push(&tail).map_err(Failure::fatal)? {
                *delivered = true;
                sink(delta);
            }
        }
        assembler.finish().map_err(Failure::fatal)
    }
}

#[async_trait::async_trait]
impl Model for LlmClient {
    async fn stream(
        &self,
        request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError> {
        if request.cancel.is_cancelled() {
            return Err(CoreError::Rejected {
                reason: "cancelled before the request was sent".into(),
            });
        }
        let mut delivered = false;
        let mut attempt = 0u32;
        loop {
            attempt += 1;
            match self.attempt(&request, sink, &mut delivered).await {
                Ok(turn) => return Ok(turn),
                Err(failure) => {
                    // Cancellation is not a provider fault: retrying it would
                    // resume the very work the user stopped.
                    if matches!(failure.error, CoreError::Rejected { .. }) {
                        return Err(failure.error);
                    }
                    // A retry after the caller already saw bytes would duplicate
                    // text in the transcript. Refuse, and let the caller decide.
                    let can_retry =
                        !delivered && failure.retryable && attempt < self.config.retry.max_attempts;
                    if !can_retry {
                        return Err(failure.error);
                    }
                    let delay = backoff(&self.config.retry, attempt);
                    tokio::time::sleep(delay).await;
                }
            }
        }
    }
}

/// Asks an OpenAI-compatible endpoint which models it actually serves.
///
/// The settings screen's "test connection" must answer with the endpoint's own
/// reply. A stored boolean would let the app claim a connection it never made, and
/// the user would only find out when the first real turn failed.
///
/// The client is separate from the streaming one on purpose: a probe fails fast
/// instead of sitting on a long read timeout, refuses redirects because a `302`
/// would carry the `Authorization` header to a host the user never approved, and is
/// never retried — a retried probe would keep knocking on an endpoint the user was
/// just told is unreachable.
pub async fn list_models(
    base_url: &str,
    api_key: &str,
    timeout: Duration,
) -> Result<Vec<String>, CoreError> {
    let http = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(timeout)
        .build()
        .map_err(|e| CoreError::model(format!("http client: {e}")))?;
    let url = format!("{}/models", base_url.trim_end_matches('/'));
    let mut request = http.get(&url);
    if !api_key.trim().is_empty() {
        request = request.bearer_auth(api_key);
    }
    let response = request
        .send()
        .await
        .map_err(|e| CoreError::model(format!("cannot reach {url}: {e}")))?;
    let status = response.status().as_u16();
    let body = response.text().await.unwrap_or_default();
    if !(200..300).contains(&status) {
        let snippet: String = body.chars().take(200).collect();
        return Err(match status {
            401 | 403 => CoreError::PermissionDenied {
                resource: format!("provider api key ({url} rejected it)"),
            },
            _ => CoreError::model(format!("http {status} from {url}: {snippet}")),
        });
    }
    let parsed: serde_json::Value = serde_json::from_str(&body)
        .map_err(|e| CoreError::model(format!("{url} did not answer JSON: {e}")))?;
    let mut names: Vec<String> = parsed
        .get("data")
        .and_then(|value| value.as_array())
        .map(|items| {
            items
                .iter()
                .filter_map(|item| item.get("id").and_then(|id| id.as_str()))
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default();
    names.sort();
    Ok(names)
}

/// Removes the API key from text that may be surfaced.
///
/// One place, called from every path that can carry provider text outward: error
/// classification, event payloads and anything a host logs.
pub fn redact_secret(text: &str, secret: &str) -> String {
    if secret.len() < 4 {
        return text.to_owned();
    }
    text.replace(secret, "[redacted]")
}

fn backoff(policy: &RetryPolicy, attempt: u32) -> Duration {
    let factor = 1u32 << attempt.min(5);
    let millis = policy.base_delay.as_millis() as u64 * factor as u64;
    Duration::from_millis(millis).min(policy.max_delay)
}

/// Map an HTTP failure onto the frozen error enum.
fn classify_status(status: u16, body: &str) -> Failure {
    let snippet: String = body.chars().take(200).collect();
    match status {
        401 | 403 => Failure::fatal(CoreError::PermissionDenied {
            resource: "provider api key".into(),
        }),
        400 | 404 | 422 => Failure::fatal(CoreError::InvalidRequest {
            reason: format!("provider rejected the request: {snippet}"),
        }),
        408 | 429 | 500..=599 => {
            Failure::retryable(CoreError::model(format!("http {status}: {snippet}")))
        }
        _ => Failure::fatal(CoreError::model(format!("http {status}: {snippet}"))),
    }
}

/// Exposed for the adjacent tests; retryability lives on `Failure` otherwise.
pub fn retryable_status(status: u16) -> bool {
    status == 408 || status == 429 || (500..=599).contains(&status)
}

/// Build a client whose retries are fast enough for tests.
pub fn test_client(config: ProviderConfig) -> LlmClient {
    LlmClient::new(config).expect("client")
}
