//! Real-provider tests.
//!
//! These talk to an actual HTTP endpoint that speaks the OpenAI chat protocol.
//! They are `#[ignore]` by default because CI has no model server, and a test
//! that silently passes when the server is absent is worse than no test.
//!
//! Run them against any OpenAI-compatible endpoint:
//!
//! ```text
//! SUNDAY_TEST_BASE_URL=http://127.0.0.1:11434/v1 \
//! SUNDAY_TEST_MODEL=qwen2.5:3b \
//! SUNDAY_TEST_API_KEY=ollama \
//!   cargo test -p sunday-llm --test real_provider -- --ignored --nocapture
//! ```

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use sunday_llm::{LlmClient, ProviderConfig, RetryPolicy};
use sunday_protocol::{Message, Model, ModelDelta, ModelRequest, ModelTurn, ToolDefinition};

fn base_url() -> String {
    std::env::var("SUNDAY_TEST_BASE_URL").unwrap_or_else(|_| "http://127.0.0.1:11434/v1".into())
}

fn model_id() -> String {
    std::env::var("SUNDAY_TEST_MODEL").unwrap_or_else(|_| "qwen2.5:3b".into())
}

fn api_key() -> String {
    std::env::var("SUNDAY_TEST_API_KEY").unwrap_or_else(|_| "test".into())
}

fn client() -> LlmClient {
    LlmClient::new(ProviderConfig::openai(base_url(), api_key())).expect("client")
}

fn request(prompt: &str) -> ModelRequest {
    ModelRequest {
        model_id: model_id(),
        messages: vec![Message::User {
            content: prompt.to_owned(),
        }],
        tools: Vec::new(),
        temperature: Some(0.0),
        max_output_tokens: Some(64),
        cancel: Default::default(),
    }
}

/// Refuse to report success when there is no server: an ignored test that runs
/// anyway must fail loudly rather than pass on an empty response.
async fn require_server() {
    let url = format!("{}/models", base_url().trim_end_matches('/'));
    let response = reqwest::get(&url).await;
    match response {
        Ok(r) if r.status().is_success() => {}
        Ok(r) => panic!("model server at {url} answered {}", r.status()),
        Err(e) => panic!(
            "no model server at {url}: {e}. Start one, or set SUNDAY_TEST_BASE_URL; \
             this test must not pass without a real provider"
        ),
    }
}

#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn streaming_delivers_text_incrementally_before_the_turn_completes() {
    require_server().await;
    let client = client();

    // Record how many chunks arrived and when the first one did.
    let first_delta_at: Arc<Mutex<Option<Instant>>> = Arc::new(Mutex::new(None));
    let chunks = Arc::new(Mutex::new(Vec::<String>::new()));
    let started = Instant::now();

    let turn = {
        let first = first_delta_at.clone();
        let sink_chunks = chunks.clone();
        let mut sink = move |delta: ModelDelta| {
            if let ModelDelta::Text(text) = delta {
                let mut guard = first.lock().unwrap();
                if guard.is_none() {
                    *guard = Some(Instant::now());
                }
                drop(guard);
                sink_chunks.lock().unwrap().push(text);
            }
        };
        client
            .stream(
                request("Count from 1 to 20, separated by spaces. Nothing else."),
                &mut sink,
            )
            .await
            .expect("stream")
    };

    let text = turn.text.unwrap_or_default();
    assert!(!text.trim().is_empty(), "the provider returned no text");
    let chunks = chunks.lock().unwrap().clone();
    assert!(
        !chunks.is_empty(),
        "no streaming deltas: the whole answer arrived as one turn"
    );
    let first_at = first_delta_at.lock().unwrap().expect("first delta");
    // A real stream reaches the caller before the turn is assembled. With a
    // 20-item answer this is a wide margin even on a slow local model.
    assert!(
        first_at <= started + Duration::from_secs(30),
        "the first delta took {:?}",
        first_at.duration_since(started)
    );
    println!(
        "streamed {} chunks, first after {:?}",
        chunks.len(),
        first_at.duration_since(started)
    );
}

#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn tool_calls_are_parsed_from_a_real_model_answer() {
    require_server().await;
    let client = client();

    let mut req = request(
        "Use the write_file tool to write the text hello into the file out.txt. Do not explain.",
    );
    req.tools = vec![ToolDefinition {
        name: "write_file".into(),
        description: "Write text to a file in the workspace.".into(),
        input_schema: serde_json::json!({
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }),
    }];

    let mut sink = |_: ModelDelta| {};
    let turn = client.stream(req, &mut sink).await.expect("stream");

    assert!(
        !turn.tool_calls.is_empty(),
        "the model did not call the tool; text was {:?}",
        turn.text
    );
    let call = &turn.tool_calls[0];
    assert_eq!(call.name, "write_file");
    assert!(
        !call.id.is_empty(),
        "a tool call needs an id to be answered"
    );
    assert!(
        call.args.get("path").is_some(),
        "the arguments did not arrive: {:?}",
        call.args
    );
    println!("tool call: {} {:?}", call.name, call.args);
}

#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn a_multi_step_tool_conversation_round_trips() {
    require_server().await;
    let client = client();
    let tools = vec![ToolDefinition {
        name: "add".into(),
        description: "Add two integers.".into(),
        input_schema: serde_json::json!({
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"]
        }),
    }];

    let mut sink = |_: ModelDelta| {};
    let first = client
        .stream(
            ModelRequest {
                model_id: model_id(),
                messages: vec![Message::User {
                    content: "What is 17 + 25? Use the add tool.".into(),
                }],
                tools: tools.clone(),
                temperature: Some(0.0),
                max_output_tokens: Some(128),
                cancel: Default::default(),
            },
            &mut sink,
        )
        .await
        .expect("first turn");
    assert!(
        !first.tool_calls.is_empty(),
        "no tool call: {:?}",
        first.text
    );
    let call = first.tool_calls[0].clone();

    // Answer the call the way the loop does, then let the model finish.
    let second = client
        .stream(
            ModelRequest {
                model_id: model_id(),
                messages: vec![
                    Message::User {
                        content: "What is 17 + 25? Use the add tool.".into(),
                    },
                    Message::AssistantToolCalls {
                        calls: vec![call.clone()],
                        content: None,
                    },
                    Message::ToolResult {
                        call_id: call.id.clone(),
                        name: call.name.clone(),
                        content: "42".into(),
                    },
                ],
                tools,
                temperature: Some(0.0),
                max_output_tokens: Some(128),
                cancel: Default::default(),
            },
            &mut sink,
        )
        .await
        .expect("second turn");

    let text = second.text.unwrap_or_default();
    assert!(
        text.contains("42"),
        "the model did not use the tool result: {text:?}"
    );
}

#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn an_unreachable_endpoint_fails_without_hanging_forever() {
    // Nothing listens on this port. The client must give up on its own.
    let mut config = ProviderConfig::openai("http://127.0.0.1:9/v1", "x");
    config.retry = RetryPolicy {
        max_attempts: 2,
        base_delay: Duration::from_millis(10),
        max_delay: Duration::from_millis(50),
    };
    let client = LlmClient::new(config).expect("client");
    let started = Instant::now();
    let mut sink = |_: ModelDelta| {};
    let result = client.stream(request("hello"), &mut sink).await;
    assert!(result.is_err(), "an unreachable endpoint must fail");
    assert!(
        started.elapsed() < Duration::from_secs(60),
        "the client hung for {:?}",
        started.elapsed()
    );
    let error = result.unwrap_err();
    println!("failed as expected in {:?}: {error}", started.elapsed());
}

#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn a_bad_model_name_fails_fast_instead_of_retrying_forever() {
    require_server().await;
    let mut config = ProviderConfig::openai(base_url(), api_key());
    config.retry.base_delay = Duration::from_millis(10);
    let client = LlmClient::new(config).expect("client");
    let started = Instant::now();
    let mut sink = |_: ModelDelta| {};
    let result = client
        .stream(
            ModelRequest {
                model_id: "definitely-not-a-model-xyz".into(),
                messages: vec![Message::User {
                    content: "hi".into(),
                }],
                tools: Vec::new(),
                temperature: None,
                max_output_tokens: Some(8),
                cancel: Default::default(),
            },
            &mut sink,
        )
        .await;
    assert!(result.is_err(), "a bogus model must fail");
    assert!(
        started.elapsed() < Duration::from_secs(30),
        "a 4xx classification must not be retried; took {:?}",
        started.elapsed()
    );
    println!(
        "rejected in {:?}: {}",
        started.elapsed(),
        result.unwrap_err()
    );
}

#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn a_cancelled_turn_stops_consuming_the_stream() {
    require_server().await;
    let client = client();

    // Press Stop from inside the sink, on the first visible token: exactly what
    // the loop does when a user hits stop while the answer streams.
    let cancel = sunday_protocol::CancelToken::new();
    let deltas = Arc::new(AtomicUsize::new(0));
    let started = Instant::now();

    let turn = {
        let in_sink = cancel.clone();
        let deltas = deltas.clone();
        let mut sink = move |delta: ModelDelta| {
            if let ModelDelta::Text(_) = delta {
                deltas.fetch_add(1, Ordering::SeqCst);
                in_sink.cancel();
            }
        };
        let mut req = request("Write a 600 word essay about the history of rivers.");
        req.max_output_tokens = Some(400);
        req.cancel = cancel.clone();
        client.stream(req, &mut sink).await
    };
    let elapsed = started.elapsed();

    assert!(
        deltas.load(Ordering::SeqCst) > 0,
        "no delta arrived, so there was nothing to cancel"
    );
    match turn {
        Ok(turn) => panic!(
            "the stream ran to completion despite the cancel ({} chars in {:?});              a cancelled read must stop, not quietly finish",
            turn.text.unwrap_or_default().len(),
            elapsed
        ),
        Err(error) => {
            // A cancel must surface as Rejected, not as a provider fault: a fault
            // would be retried and would resume the work the user stopped.
            assert!(
                matches!(error, sunday_protocol::CoreError::Rejected { .. }),
                "a cancel surfaced as {error:?}, which a caller would treat as a provider fault"
            );
            println!(
                "stopped after {} deltas in {:?}: {error}",
                deltas.load(Ordering::SeqCst),
                elapsed
            );
        }
    }
}

/// Cancelling before the request is sent must not open a connection at all.
#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn a_pre_cancelled_request_never_reaches_the_provider() {
    // No require_server() on purpose: if this opened a connection it would fail
    // with a transport error instead of Rejected, which is the distinction under
    // test. A port nothing listens on makes that obvious.
    let client =
        LlmClient::new(ProviderConfig::openai("http://127.0.0.1:9/v1", "x")).expect("client");
    let cancel = sunday_protocol::CancelToken::new();
    cancel.cancel();
    let mut req = request("this must never be sent");
    req.cancel = cancel;
    let mut sink = |_: ModelDelta| {};
    let started = Instant::now();
    let error = client
        .stream(req, &mut sink)
        .await
        .expect_err("must not send");
    assert!(
        matches!(error, sunday_protocol::CoreError::Rejected { .. }),
        "a pre-cancelled request produced {error:?} instead of a clean rejection"
    );
    assert!(
        started.elapsed() < Duration::from_secs(2),
        "a pre-cancelled request took {:?}, which suggests it went to the network",
        started.elapsed()
    );
    println!("pre-cancelled rejected in {:?}: {error}", started.elapsed());
}

/// A direct comparison so the report can quote a number instead of an opinion.
#[tokio::test]
#[ignore = "needs a real OpenAI-compatible endpoint"]
async fn a_turn_reports_wall_clock_and_usage() {
    require_server().await;
    let client = client();
    let mut sink = |_: ModelDelta| {};
    let started = Instant::now();
    let turn: ModelTurn = client
        .stream(request("Say the single word: ready"), &mut sink)
        .await
        .expect("stream");
    println!(
        "elapsed {:?}, usage {:?}, text {:?}",
        started.elapsed(),
        turn.usage,
        turn.text
    );
    assert!(turn.text.is_some());
}
