//! Trial migration A acceptance tests.
//!
//! These run against a real TCP server speaking real HTTP, so streaming,
//! connection resets, idle timeouts and status handling are exercised for real
//! rather than mocked at the function boundary.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use sunday_llm::{sse, LlmClient, ProviderConfig, RetryPolicy};
use sunday_protocol::{CoreError, Message, Model, ModelDelta, ModelRequest, ToolDefinition};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;

/// CRLFCRLF, as bytes. Written as numbers so no escaping can be mangled.
const HEADER_END: [u8; 4] = [0x0d, 0x0a, 0x0d, 0x0a];

#[derive(Clone)]
struct Script {
    status: u16,
    /// (delay before this chunk, chunk bytes)
    chunks: Vec<(u64, String)>,
    /// Real providers stream with chunked transfer encoding. Close-delimited
    /// bodies cannot signal truncation at all, which the tests below rely on.
    chunked: bool,
    /// Deliberately omit the terminating zero-length chunk.
    truncate: bool,
}

impl Script {
    fn sse(chunks: Vec<(u64, String)>) -> Self {
        Self {
            status: 200,
            chunks,
            chunked: true,
            truncate: false,
        }
    }
    fn sse_truncated(chunks: Vec<(u64, String)>) -> Self {
        Self {
            status: 200,
            chunks,
            chunked: true,
            truncate: true,
        }
    }
    fn sse_close_delimited(chunks: Vec<(u64, String)>) -> Self {
        Self {
            status: 200,
            chunks,
            chunked: false,
            truncate: false,
        }
    }
    fn status_only(status: u16, body: &str) -> Self {
        Self {
            status,
            chunks: vec![(0, body.to_owned())],
            chunked: false,
            truncate: false,
        }
    }
}

struct Server {
    base_url: String,
    hits: Arc<AtomicUsize>,
}

async fn spawn(scripts: Vec<Script>) -> Server {
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let hits = Arc::new(AtomicUsize::new(0));
    let counter = hits.clone();

    tokio::spawn(async move {
        let mut index = 0usize;
        loop {
            let Ok((mut socket, _)) = listener.accept().await else {
                break;
            };
            counter.fetch_add(1, Ordering::SeqCst);
            let script = scripts
                .get(index)
                .cloned()
                .unwrap_or(Script::status_only(599, "no script"));
            index += 1;

            tokio::spawn(async move {
                // Read the whole request, not just the headers. Replying and
                // closing while the client is still writing its body makes the
                // server send an RST that destroys the response, which shows up
                // as a bogus transport error under parallel test load.
                let mut received: Vec<u8> = Vec::new();
                let mut chunk = [0u8; 8192];
                // Read headers first; the loop hands back the header length.
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
                let head = String::from_utf8_lossy(&received[..head_end]).to_ascii_lowercase();
                let want: usize = head
                    .lines()
                    .find_map(|line| line.strip_prefix("content-length:"))
                    .and_then(|value| value.trim().parse().ok())
                    .unwrap_or(0);
                let target = head_end + want;
                while received.len() < target {
                    let Ok(n) = socket.read(&mut chunk).await else {
                        break;
                    };
                    if n == 0 {
                        break;
                    }
                    received.extend_from_slice(&chunk[..n]);
                }

                let reason = match script.status {
                    200 => "OK",
                    401 => "Unauthorized",
                    400 => "Bad Request",
                    429 => "Too Many Requests",
                    500 => "Internal Server Error",
                    _ => "Error",
                };
                let encoding = if script.chunked {
                    "Transfer-Encoding: chunked\r\n"
                } else {
                    ""
                };
                let head = format!(
                    "HTTP/1.1 {} {}\r\nContent-Type: text/event-stream\r\n{}Connection: close\r\n\r\n",
                    script.status, reason, encoding
                );
                if socket.write_all(head.as_bytes()).await.is_err() {
                    return;
                }
                for (delay, chunk) in script.chunks {
                    if delay > 0 {
                        tokio::time::sleep(Duration::from_millis(delay)).await;
                    }
                    let frame = if script.chunked {
                        format!("{:x}\r\n{}\r\n", chunk.len(), chunk)
                    } else {
                        chunk
                    };
                    if socket.write_all(frame.as_bytes()).await.is_err() {
                        return;
                    }
                    let _ = socket.flush().await;
                }
                if script.chunked && !script.truncate {
                    let _ = socket.write_all(b"0\r\n\r\n").await;
                }
                let _ = socket.flush().await;
                let _ = socket.shutdown().await;
            });
        }
    });

    Server {
        base_url: format!("http://{addr}"),
        hits,
    }
}

fn openai_request() -> ModelRequest {
    ModelRequest {
        model_id: "gpt-test".into(),
        messages: vec![
            Message::System {
                content: "be careful".into(),
            },
            Message::User {
                content: "create a file".into(),
            },
        ],
        tools: vec![ToolDefinition {
            name: "write_file".into(),
            description: "write a file".into(),
            input_schema: serde_json::json!({"type": "object"}),
        }],
        temperature: Some(0.2),
        max_output_tokens: Some(64),
        cancel: Default::default(),
    }
}

fn fast(config: ProviderConfig) -> ProviderConfig {
    ProviderConfig {
        retry: RetryPolicy {
            max_attempts: 3,
            base_delay: Duration::from_millis(10),
            max_delay: Duration::from_millis(50),
        },
        ..config
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn openai_streams_text_across_split_tcp_frames() {
    // The JSON frame is deliberately split mid-token to prove the SSE parser
    // and the assembler survive arbitrary chunk boundaries.
    let server = spawn(vec![Script::sse(vec![
        (0, "data: {\"choices\":[{\"delta\":{\"content\":\"你".into()),
        (0, "好\"}}]}\n\n".into()),
        (0, "data: {\"choices\":[{\"delta\":{\"tool_calls\":[{\"index\":0,\"id\":\"call_1\",".into()),
        (0, "\"function\":{\"name\":\"write_file\",\"arguments\":\"{\\\"path\\\":\\\"a.txt\\\"}\"}}]}}]}\n\n".into()),
        (0, "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":5}}\n\n".into()),
        (0, "data: [DONE]\n\n".into()),
    ])])
    .await;

    let client =
        LlmClient::new(fast(ProviderConfig::openai(server.base_url.clone(), "k"))).unwrap();
    let mut deltas = Vec::new();
    let mut sink = |d: ModelDelta| deltas.push(d);
    let turn = client.stream(openai_request(), &mut sink).await.unwrap();

    assert_eq!(turn.text.as_deref(), Some("你好"));
    assert_eq!(turn.tool_calls.len(), 1);
    assert_eq!(turn.tool_calls[0].name, "write_file");
    assert_eq!(turn.tool_calls[0].args["path"], "a.txt");
    assert_eq!(turn.usage.unwrap().input_tokens, 12);

    let text: String = deltas
        .iter()
        .filter_map(|d| match d {
            ModelDelta::Text(t) => Some(t.as_str()),
            _ => None,
        })
        .collect();
    assert_eq!(text, "你好");
    assert_eq!(server.hits.load(Ordering::SeqCst), 1);
}

#[tokio::test(flavor = "multi_thread")]
async fn anthropic_streams_text_tool_use_and_usage() {
    let server = spawn(vec![Script::sse(vec![
        (0, "event: message_start\ndata: {\"type\":\"message_start\",\"message\":{\"usage\":{\"input_tokens\":9}}}\n\n".into()),
        (0, "event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":0,\"content_block\":{\"type\":\"text\"}}\n\n".into()),
        (0, "event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":0,\"delta\":{\"type\":\"text_delta\",\"text\":\"先看一下\"}}\n\n".into()),
        (0, "event: content_block_start\ndata: {\"type\":\"content_block_start\",\"index\":1,\"content_block\":{\"type\":\"tool_use\",\"id\":\"toolu_1\",\"name\":\"write_file\"}}\n\n".into()),
        (0, "event: content_block_delta\ndata: {\"type\":\"content_block_delta\",\"index\":1,\"delta\":{\"type\":\"input_json_delta\",\"partial_json\":\"{\\\"path\\\":\\\"b.txt\\\"}\"}}\n\n".into()),
        (0, "event: message_delta\ndata: {\"type\":\"message_delta\",\"delta\":{},\"usage\":{\"output_tokens\":4}}\n\n".into()),
        (0, "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n".into()),
    ])])
    .await;

    let client = LlmClient::new(fast(ProviderConfig::anthropic(
        server.base_url.clone(),
        "k",
    )))
    .unwrap();
    let mut deltas = Vec::new();
    let mut sink = |d: ModelDelta| deltas.push(d);
    let turn = client.stream(openai_request(), &mut sink).await.unwrap();

    assert_eq!(turn.text.as_deref(), Some("先看一下"));
    assert_eq!(turn.tool_calls[0].id, "toolu_1");
    assert_eq!(turn.tool_calls[0].args["path"], "b.txt");
    assert_eq!(turn.usage.unwrap().output_tokens, 4);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_500_is_retried_and_then_succeeds() {
    let server = spawn(vec![
        Script::status_only(500, "upstream exploded"),
        Script::sse(vec![(
            0,
            "data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\n".into(),
        )]),
    ])
    .await;

    let client =
        LlmClient::new(fast(ProviderConfig::openai(server.base_url.clone(), "k"))).unwrap();
    let mut deltas = Vec::new();
    let mut sink = |d: ModelDelta| deltas.push(d);
    let turn = client.stream(openai_request(), &mut sink).await.unwrap();

    assert_eq!(turn.text.as_deref(), Some("ok"));
    assert_eq!(
        server.hits.load(Ordering::SeqCst),
        2,
        "one failure plus one success"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_401_is_fatal_and_not_retried() {
    let server = spawn(vec![Script::status_only(401, "bad key")]).await;
    let client =
        LlmClient::new(fast(ProviderConfig::openai(server.base_url.clone(), "k"))).unwrap();
    let mut sink = |_d: ModelDelta| {};
    let err = client
        .stream(openai_request(), &mut sink)
        .await
        .unwrap_err();
    assert!(matches!(err, CoreError::PermissionDenied { .. }));
    assert_eq!(
        server.hits.load(Ordering::SeqCst),
        1,
        "a bad key must not be retried"
    );
}

#[tokio::test(flavor = "multi_thread")]
async fn a_400_is_reported_as_invalid_request() {
    let server = spawn(vec![Script::status_only(400, "bad schema")]).await;
    let client =
        LlmClient::new(fast(ProviderConfig::openai(server.base_url.clone(), "k"))).unwrap();
    let mut sink = |_d: ModelDelta| {};
    let err = client
        .stream(openai_request(), &mut sink)
        .await
        .unwrap_err();
    assert!(matches!(err, CoreError::InvalidRequest { .. }));
}

#[tokio::test(flavor = "multi_thread")]
async fn a_truncated_chunked_stream_is_an_error_and_is_not_retried() {
    // Real providers use chunked encoding; a missing terminator is detectable.
    let server = spawn(vec![
        Script::sse_truncated(vec![(
            0,
            "data: {\"choices\":[{\"delta\":{\"content\":\"part\"}}]}\n\n".into(),
        )]),
        Script::sse(vec![(
            0,
            "data: {\"choices\":[{\"delta\":{\"content\":\"第二次\"}}]}\n\n".into(),
        )]),
    ])
    .await;

    let client =
        LlmClient::new(fast(ProviderConfig::openai(server.base_url.clone(), "k"))).unwrap();
    let mut deltas = Vec::new();
    let mut sink = |d: ModelDelta| deltas.push(d);
    let result = client.stream(openai_request(), &mut sink).await;

    assert!(
        result.is_err(),
        "a truncated chunked stream must not look like success"
    );
    assert_eq!(
        server.hits.load(Ordering::SeqCst),
        1,
        "retrying would duplicate the text the caller already saw"
    );
    assert_eq!(deltas.len(), 1, "the delivered delta is real and must stay");
}

#[tokio::test(flavor = "multi_thread")]
async fn a_close_delimited_stream_end_is_indistinguishable_from_success() {
    // Documented limitation, not a defect we can fix on the client side:
    // without chunked encoding or a length, closing the socket is a valid end.
    let server = spawn(vec![Script::sse_close_delimited(vec![(
        0,
        "data: {\"choices\":[{\"delta\":{\"content\":\"only\"}}]}\n\n".into(),
    )])])
    .await;

    let client =
        LlmClient::new(fast(ProviderConfig::openai(server.base_url.clone(), "k"))).unwrap();
    let mut deltas = Vec::new();
    let mut sink = |d: ModelDelta| deltas.push(d);
    let turn = client.stream(openai_request(), &mut sink).await.unwrap();
    assert_eq!(turn.text.as_deref(), Some("only"));
    assert_eq!(deltas.len(), 1);
}

#[tokio::test(flavor = "multi_thread")]
async fn a_stalled_stream_times_out() {
    let server = spawn(vec![Script::sse(vec![
        (
            0,
            "data: {\"choices\":[{\"delta\":{\"content\":\"a\"}}]}\n\n".into(),
        ),
        (400, ": keep-alive\n\n".into()),
    ])])
    .await;

    let mut config = fast(ProviderConfig::openai(server.base_url.clone(), "k"));
    config.idle_timeout = Duration::from_millis(80);
    config.retry.max_attempts = 1;
    let client = LlmClient::new(config).unwrap();

    let mut sink = |_d: ModelDelta| {};
    let err = client
        .stream(openai_request(), &mut sink)
        .await
        .unwrap_err();
    match err {
        CoreError::Model { reason } => assert!(reason.contains("idle"), "got: {reason}"),
        other => panic!("expected an idle-timeout model error, got {other:?}"),
    }
}

#[tokio::test(flavor = "multi_thread")]
async fn a_malformed_frame_is_fatal_and_not_retried() {
    let server = spawn(vec![Script::sse(vec![(0, "data: {not json}\n\n".into())])]).await;
    let client =
        LlmClient::new(fast(ProviderConfig::openai(server.base_url.clone(), "k"))).unwrap();
    let mut sink = |_d: ModelDelta| {};
    let err = client
        .stream(openai_request(), &mut sink)
        .await
        .unwrap_err();
    assert!(matches!(err, CoreError::Model { .. }));
    assert_eq!(server.hits.load(Ordering::SeqCst), 1);
}

#[tokio::test(flavor = "multi_thread")]
async fn retries_are_bounded_by_the_policy() {
    let server = spawn(vec![
        Script::status_only(500, "a"),
        Script::status_only(500, "b"),
        Script::status_only(500, "c"),
    ])
    .await;
    let mut config = fast(ProviderConfig::openai(server.base_url.clone(), "k"));
    config.retry.max_attempts = 3;
    let client = LlmClient::new(config).unwrap();
    let mut sink = |_d: ModelDelta| {};
    assert!(client.stream(openai_request(), &mut sink).await.is_err());
    assert_eq!(server.hits.load(Ordering::SeqCst), 3);
}

#[test]
fn sse_parser_is_independent_of_chunking() {
    let payload = "event: a\ndata: one\n\ndata: two\n\n";
    let whole = {
        let mut p = sse::SseParser::new();
        p.push(payload)
    };
    for split in 1..payload.len() {
        let mut p = sse::SseParser::new();
        let mut got = p.push(&payload[..split]);
        got.extend(p.push(&payload[split..]));
        if let Some(tail) = p.finish() {
            got.push(tail);
        }
        assert_eq!(got, whole, "split at {split} changed the parse");
    }
}
