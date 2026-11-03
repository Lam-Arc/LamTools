//! Compaction quality against a real summariser.
//!
//! The existing unit tests prove compaction does not lose the task statement.
//! They say nothing about whether the summary is *useful*, which is the thing a
//! user actually experiences. These tests measure that with a real model, so
//! they are ignored unless a provider is configured.
//!
//! ```text
//! SUNDAY_TEST_BASE_URL=http://127.0.0.1:11434/v1 SUNDAY_TEST_MODEL=qwen2.5:3b \
//!   cargo test -p sunday-context --test compaction_quality -- --ignored --nocapture
//! ```

use sunday_context::{compact, estimate_tokens, needs_compaction, Policy, Summarizer};
use sunday_llm::{LlmClient, ProviderConfig};
use sunday_protocol::{CoreError, Message, Model};

/// Asks the provider to compress a chunk of transcript. This is the real
/// summariser an assembled core would use, not a fixture.
struct ModelSummarizer {
    client: LlmClient,
    model_id: String,
}

impl Summarizer for ModelSummarizer {
    fn summarize(&self, dropped: &[Message]) -> Result<String, CoreError> {
        let transcript = render(dropped);
        let request = sunday_protocol::ModelRequest {
            model_id: self.model_id.clone(),
            messages: vec![
                Message::System {
                    content: "You compress a conversation transcript for an agent's memory. \
                              Keep every fact that a later step could still need: file paths, \
                              decisions, numbers, names, open questions. Drop pleasantries and \
                              repetition. Answer with the summary only."
                        .into(),
                },
                Message::User {
                    content: transcript,
                },
            ],
            tools: Vec::new(),
            temperature: Some(0.0),
            max_output_tokens: Some(500),
            cancel: Default::default(),
        };
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| CoreError::model(format!("runtime: {e}")))?;
        let turn = runtime.block_on(async {
            let mut sink = |_: sunday_protocol::ModelDelta| {};
            self.client.stream(request, &mut sink).await
        })?;
        turn.text
            .ok_or_else(|| CoreError::model("the summariser returned no text"))
    }
}

fn render(messages: &[Message]) -> String {
    let mut out = String::new();
    for message in messages {
        match message {
            Message::System { content } => out.push_str(&format!("system: {content}\n")),
            Message::User { content } => out.push_str(&format!("user: {content}\n")),
            Message::UserMultimodal { content, .. } => out.push_str(&format!("user: {content}\n")),
            Message::Assistant { content } => out.push_str(&format!("assistant: {content}\n")),
            Message::AssistantToolCalls { calls, .. } => {
                out.push_str(&format!("assistant called {calls:?}\n"))
            }
            Message::ToolResult { name, content, .. } => {
                out.push_str(&format!("tool {name}: {content}\n"))
            }
        }
    }
    out
}

fn base_url() -> String {
    std::env::var("SUNDAY_TEST_BASE_URL").unwrap_or_else(|_| "http://127.0.0.1:11434/v1".into())
}

fn model_id() -> String {
    std::env::var("SUNDAY_TEST_MODEL").unwrap_or_else(|_| "qwen2.5:3b".into())
}

fn summarizer() -> ModelSummarizer {
    let client = LlmClient::new(ProviderConfig::openai(base_url(), "test")).expect("client");
    ModelSummarizer {
        client,
        model_id: model_id(),
    }
}

/// A transcript whose later steps depend on early specifics. Anything the
/// summary drops here would cause a real mistake downstream.
fn long_transcript() -> Vec<Message> {
    let mut messages = vec![
        Message::System {
            content: "You are Sunday.".into(),
        },
        Message::User {
            content: "Refactor the importer so it stops dropping rows; the bug report says \
                       exactly 17 rows vanish when the CSV has a trailing comma."
                .into(),
        },
    ];
    // A realistic middle: tool output and reasoning that must not all survive,
    // but whose key facts must.
    for index in 0..10 {
        messages.push(Message::Assistant {
            content: format!("step {index}: reading src/importer/parser.py to find the split"),
        });
        messages.push(Message::ToolResult {
            call_id: format!("call-{index}"),
            name: "read_file".into(),
            content: format!(
                "line {}: rows = line.split(',')  # splits on every comma\n\
                 note: the fix must keep the clock at 30 seconds and the batch size at 500",
                40 + index
            ),
        });
    }
    messages.push(Message::Assistant {
        content: "the root cause is an unconditional split on comma".into(),
    });
    messages
}

fn policy() -> Policy {
    Policy {
        trigger_tokens: 1,
        keep_recent: 2,
        max_summary_chars: 2_000,
    }
}

#[test]
#[ignore = "needs a real summariser"]
fn the_summary_keeps_the_facts_a_later_step_needs() {
    let messages = long_transcript();
    let before = estimate_tokens(&messages);
    let result = compact(&messages, &policy(), &summarizer())
        .expect("compaction")
        .expect("compaction should have triggered");
    let after = estimate_tokens(&result.messages);

    println!(
        "{} messages -> {} (removed {}), ~{} tokens -> ~{} tokens",
        messages.len(),
        result.messages.len(),
        result.removed_messages,
        before,
        after
    );
    let summary = result
        .messages
        .iter()
        .find_map(|m| match m {
            Message::User { content } if content.contains("Summary of earlier") => Some(content),
            _ => None,
        })
        .cloned()
        .or_else(|| {
            // Fall back to whatever the compacted list holds right after the
            // pinned head, so the assertion message stays useful.
            result.messages.get(2).and_then(|m| match m {
                Message::User { content } => Some(content.clone()),
                _ => None,
            })
        })
        .unwrap_or_default();
    println!("summary:\n{summary}");

    // Two different guarantees, measured separately because they are achieved
    // by different mechanisms and one must not cover for the other:
    //
    // 1. Facts only present in the dropped region must survive *in the summary*.
    //    `30 seconds` and `500` appear nowhere else in the transcript.
    let lower = summary.to_lowercase();
    assert!(
        lower.contains("500"),
        "the summary lost the batch size, which only existed in the dropped tool output: {summary}"
    );
    assert!(
        lower.contains("30"),
        "the summary lost the clock limit, which only existed in the dropped tool output: {summary}"
    );

    // 2. The bug definition must survive somewhere in the compacted list. It is
    //    pinned as the task statement rather than summarised, which is the
    //    intended design: the task is never something compaction may rewrite.
    let kept: String = result
        .messages
        .iter()
        .filter_map(|m| match m {
            Message::User { content } | Message::Assistant { content } => Some(content.clone()),
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("\n");
    assert!(
        kept.contains("17"),
        "the row count that defines the bug vanished from the compacted conversation: {kept}"
    );

    // It must also actually be smaller, or compaction achieved nothing.
    assert!(
        after < before,
        "compaction did not reduce the estimate: {before} -> {after}"
    );
}

#[test]
#[ignore = "needs a real summariser"]
fn compaction_leaves_the_task_statement_intact() {
    let messages = long_transcript();
    let result = compact(&messages, &policy(), &summarizer())
        .expect("compaction")
        .expect("compaction should have triggered");

    // The system prompt and the original task must survive verbatim: summarising
    // the task away is how an agent forgets what it was asked to do.
    assert!(matches!(&result.messages[0], Message::System { .. }));
    match &result.messages[1] {
        Message::User { content } => assert!(
            content.contains("17 rows"),
            "the task statement was altered: {content}"
        ),
        other => panic!("the task statement is gone: {other:?}"),
    }
}

#[test]
#[ignore = "needs a real summariser"]
fn a_summary_that_runs_away_is_capped() {
    let messages = long_transcript();
    let tight = Policy {
        trigger_tokens: 1,
        keep_recent: 2,
        max_summary_chars: 200,
    };
    let result = compact(&messages, &tight, &summarizer())
        .expect("compaction")
        .expect("compaction should have triggered");
    assert!(
        result.summary_chars <= 200,
        "the summary ignored its cap: {} chars",
        result.summary_chars
    );
}

#[test]
#[ignore = "needs a real summariser"]
fn a_short_conversation_is_not_compacted() {
    let messages = vec![
        Message::User {
            content: "hi".into(),
        },
        Message::Assistant {
            content: "hello".into(),
        },
    ];
    let result = compact(&messages, &policy(), &summarizer()).expect("compaction");
    assert!(result.is_none(), "a two message conversation was compacted");
    assert!(!needs_compaction(&messages, &Policy::default()));
}
