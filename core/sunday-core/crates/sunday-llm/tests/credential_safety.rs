//! Negative verification at the transport boundary.
//!
//! Four ways an API key leaves the host it was approved for, each tested against a
//! real socket rather than a mocked client:
//!
//! 1. a redirect to another origin,
//! 2. a redirect on the same origin (still not followed: an inference API has no
//!    reason to redirect, so any 3xx is a refusal, not a hint),
//! 3. a certificate nobody signed,
//! 4. an error body that echoes the key back.
//!
//! The claim in each case is concrete: the second host records zero requests, the
//! TLS handshake never completes, and the key is absent from the error the user
//! would see or paste into a ticket.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use sunday_llm::{LlmClient, ProviderConfig, RetryPolicy};
use sunday_protocol::{CoreError, Message, Model, ModelDelta, ModelRequest, ToolDefinition};

const KEY: &str = "sk-live-7c2f9a41d6e8b035";
const HEADER_END: [u8; 4] = [0x0d, 0x0a, 0x0d, 0x0a];

fn request() -> ModelRequest {
    ModelRequest {
        model_id: "gpt-test".into(),
        messages: vec![Message::User {
            content: "hello".into(),
        }],
        tools: Vec::<ToolDefinition>::new(),
        temperature: None,
        max_output_tokens: Some(16),
        cancel: Default::default(),
    }
}

fn single_attempt(config: ProviderConfig) -> ProviderConfig {
    // One attempt, so a test that asserts "the key reached nobody" cannot be
    // satisfied by a retry that also reached nobody.
    ProviderConfig {
        retry: RetryPolicy {
            max_attempts: 1,
            base_delay: Duration::from_millis(10),
            max_delay: Duration::from_millis(20),
        },
        ..config
    }
}

/// A real TCP server that answers every request with the same bytes and records
/// what it saw.
#[derive(Clone)]
struct Recorder {
    base: String,
    hits: Arc<AtomicUsize>,
    request_heads: Arc<Mutex<Vec<String>>>,
}

impl Recorder {
    fn origin(&self) -> String {
        self.base.clone()
    }

    /// The raw request line plus headers of every request received.
    fn seen(&self) -> Vec<String> {
        self.request_heads.lock().expect("lock").clone()
    }

    fn headers_contain(&self, needle: &str) -> bool {
        self.seen().iter().any(|head| head.contains(needle))
    }
}

async fn spawn_recording(response: impl Fn(&str) -> String + Send + Sync + 'static) -> Recorder {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let addr = listener.local_addr().expect("addr");
    let hits = Arc::new(AtomicUsize::new(0));
    let heads = Arc::new(Mutex::new(Vec::new()));
    let counter = Arc::clone(&hits);
    let record = Arc::clone(&heads);
    let response = Arc::new(response);

    tokio::spawn(async move {
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                break;
            };
            counter.fetch_add(1, Ordering::SeqCst);
            let record = Arc::clone(&record);
            let response = Arc::clone(&response);
            tokio::spawn(async move {
                // Read headers, then the body the Content-Length promises. Replying
                // while the client is still writing makes the server send an RST,
                // which destroys the response and turns a redirect test into a
                // meaningless transport error.
                let mut received = Vec::new();
                let mut chunk = [0u8; 8192];
                let head_end = loop {
                    let Ok(n) = socket.read(&mut chunk).await else {
                        return;
                    };
                    if n == 0 {
                        return;
                    }
                    received.extend_from_slice(&chunk[..n]);
                    if let Some(pos) = received.windows(4).position(|w| w == HEADER_END) {
                        break pos + 4;
                    }
                    if received.len() > 65536 {
                        return;
                    }
                };
                let head = String::from_utf8_lossy(&received[..head_end]).to_string();
                let length = head
                    .lines()
                    .find_map(|line| {
                        let lower = line.to_ascii_lowercase();
                        lower
                            .strip_prefix("content-length:")
                            .map(|value| value.trim().to_owned())
                    })
                    .and_then(|value| value.parse::<usize>().ok())
                    .unwrap_or(0);
                while received.len() < head_end + length {
                    let Ok(n) = socket.read(&mut chunk).await else {
                        return;
                    };
                    if n == 0 {
                        break;
                    }
                    received.extend_from_slice(&chunk[..n]);
                }
                record.lock().expect("lock").push(head.clone());
                let _ = socket.write_all(response(&head).as_bytes()).await;
                let _ = socket.flush().await;
                // A short drain keeps the close from racing the client's read.
                let mut tail = [0u8; 256];
                let _ =
                    tokio::time::timeout(Duration::from_millis(50), socket.read(&mut tail)).await;
            });
        }
    });

    Recorder {
        base: format!("http://127.0.0.1:{}", addr.port()),
        hits,
        request_heads: heads,
    }
}

async fn ask(client: &LlmClient) -> Result<(), CoreError> {
    let mut sink = |_: ModelDelta| {};
    client.stream(request(), &mut sink).await.map(|_| ())
}

/// A `302` to another origin is the classic way an `Authorization` header moves to
/// a host the user never approved.
#[tokio::test(flavor = "multi_thread")]
async fn a_cross_origin_redirect_never_reaches_the_other_host() {
    // The collector is started first so its port is knowable.
    let collector =
        spawn_recording(|_| "HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n".to_string()).await;

    let redirect_target = format!("{}/v1/chat/completions", collector.origin());
    let gateway = spawn_recording(move |_| {
        format!("HTTP/1.1 302 Found\r\nlocation: {redirect_target}\r\ncontent-length: 0\r\n\r\n")
    })
    .await;

    let client = LlmClient::new(single_attempt(ProviderConfig::openai(
        format!("{}/v1", gateway.origin()),
        KEY,
    )))
    .expect("client");

    let error = ask(&client).await.expect_err("a redirect must not succeed");
    assert_eq!(
        gateway.hits.load(Ordering::SeqCst),
        1,
        "the request did not reach the server it was addressed to"
    );
    assert_eq!(
        collector.hits.load(Ordering::SeqCst),
        0,
        "the client followed a redirect to another origin, carrying the API key"
    );
    assert!(
        !collector.headers_contain(KEY),
        "the second origin saw the key"
    );
    assert!(
        !format!("{error:?}").contains(KEY),
        "the error text carries the key: {error:?}"
    );
}

/// Same origin, different path. Still not followed, and deliberately so: if a
/// redirect is acceptable at all, the rule becomes "it depends", which is exactly
/// the kind of rule that is wrong at the one moment it matters.
#[tokio::test(flavor = "multi_thread")]
async fn a_same_origin_redirect_is_also_refused() {
    let server = spawn_recording(|head| {
        if head.contains("/moved") {
            "HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n".to_string()
        } else {
            "HTTP/1.1 307 Temporary Redirect\r\nlocation: /moved\r\ncontent-length: 0\r\n\r\n"
                .to_string()
        }
    })
    .await;

    let client = LlmClient::new(single_attempt(ProviderConfig::openai(
        format!("{}/v1", server.origin()),
        KEY,
    )))
    .expect("client");

    ask(&client).await.expect_err("a redirect must not succeed");
    assert_eq!(
        server.hits.load(Ordering::SeqCst),
        1,
        "a 307 was followed even though redirects are disabled"
    );
}

/// A certificate that no trusted authority signed must abort the handshake. The
/// server counts a completed handshake, so the assertion is "the client refused to
/// talk", not "the error message looked right".
#[tokio::test(flavor = "multi_thread")]
async fn an_unsigned_certificate_aborts_the_handshake() {
    use rustls::pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer};
    use rustls::ServerConfig;
    use tokio::net::TcpListener;
    use tokio_rustls::TlsAcceptor;

    let cert = CertificateDer::from(
        std::fs::read("tests/fixtures/self-signed-cert.der").expect("cert fixture"),
    );
    let key = PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(
        std::fs::read("tests/fixtures/self-signed-key.der").expect("key fixture"),
    ));
    let provider = Arc::new(rustls::crypto::ring::default_provider());
    let config = ServerConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()
        .expect("versions")
        .with_no_client_auth()
        .with_single_cert(vec![cert], key)
        .expect("server config");

    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
    let port = listener.local_addr().expect("addr").port();
    let completed = Arc::new(AtomicUsize::new(0));
    let counter = Arc::clone(&completed);
    let acceptor = TlsAcceptor::from(Arc::new(config));
    tokio::spawn(async move {
        loop {
            let Ok((socket, _)) = listener.accept().await else {
                break;
            };
            let acceptor = acceptor.clone();
            let counter = Arc::clone(&counter);
            tokio::spawn(async move {
                if acceptor.accept(socket).await.is_ok() {
                    counter.fetch_add(1, Ordering::SeqCst);
                }
            });
        }
    });

    let client = LlmClient::new(single_attempt(ProviderConfig::openai(
        format!("https://127.0.0.1:{port}/v1"),
        KEY,
    )))
    .expect("client");

    let error = ask(&client)
        .await
        .expect_err("an unsigned certificate must fail");
    assert_eq!(
        completed.load(Ordering::SeqCst),
        0,
        "the TLS handshake completed against a self-signed certificate"
    );
    assert!(
        matches!(error, CoreError::Model { .. }),
        "an unsigned certificate should fail as a transport error, got {error:?}"
    );
    assert!(
        !format!("{error:?}").contains(KEY),
        "the TLS error carries the key: {error:?}"
    );
}

/// Provider error bodies are untrusted text, and a careless gateway quotes the
/// credential it just received. A `400` puts that body into the error message, so
/// this is the path where redaction has to hold.
#[tokio::test(flavor = "multi_thread")]
async fn an_error_body_that_echoes_the_key_is_redacted() {
    let server = spawn_recording(|head| {
        // Exactly what a careless provider does: quote the request back.
        let echoed = head
            .lines()
            .find_map(|line| {
                let lower = line.to_ascii_lowercase();
                lower
                    .strip_prefix("authorization: bearer ")
                    .map(|_| line["authorization: bearer ".len()..].trim().to_owned())
            })
            .unwrap_or_default();
        let body = format!("{{\"error\":\"invalid api key\",\"received\":\"{echoed}\"}}");
        format!(
            "HTTP/1.1 400 Bad Request\r\ncontent-type: application/json\r\ncontent-length: {}\r\n\r\n{}",
            body.len(),
            body
        )
    })
    .await;

    let client = LlmClient::new(single_attempt(ProviderConfig::openai(
        format!("{}/v1", server.origin()),
        KEY,
    )))
    .expect("client");

    let error = ask(&client).await.expect_err("400 must fail");
    assert!(
        server.headers_contain(KEY),
        "the fixture did not actually send the key, so redaction was not exercised"
    );
    let rendered = format!("{error:?}");
    assert!(
        !rendered.contains(KEY),
        "the provider echo carried the key into the error: {rendered}"
    );
    // Redacted, not omitted: the message still has to be useful, otherwise "no key
    // in the error" would be satisfied by throwing the body away.
    assert!(
        rendered.contains("[redacted]"),
        "the body was dropped rather than redacted: {rendered}"
    );
    assert!(
        rendered.contains("invalid api key"),
        "the useful part of the provider message was lost: {rendered}"
    );
    assert!(
        matches!(error, CoreError::InvalidRequest { .. }),
        "400 should classify as an invalid request, got {error:?}"
    );
}

/// A permission failure must not quote the provider's body at all. There is nothing
/// in it the user can act on, and every word of it is untrusted.
#[tokio::test(flavor = "multi_thread")]
async fn a_permission_failure_does_not_quote_the_provider_body() {
    let server = spawn_recording(|head| {
        let echoed = head.replace('\n', " ").replace('"', "'");
        let body = format!("{{\"error\":\"bad key\",\"request\":\"{echoed}\"}}");
        format!(
            "HTTP/1.1 401 Unauthorized\r\ncontent-type: application/json\r\ncontent-length: {}\r\n\r\n{}",
            body.len(),
            body
        )
    })
    .await;

    let client = LlmClient::new(single_attempt(ProviderConfig::openai(
        format!("{}/v1", server.origin()),
        KEY,
    )))
    .expect("client");

    let error = ask(&client).await.expect_err("401 must fail");
    let rendered = format!("{error:?}");
    assert!(
        matches!(error, CoreError::PermissionDenied { .. }),
        "401 should classify as a permission failure, got {error:?}"
    );
    assert!(
        !rendered.contains("bad key"),
        "a permission failure quoted the provider body: {rendered}"
    );
    assert!(
        !rendered.contains(KEY),
        "the key reached the error: {rendered}"
    );
}
