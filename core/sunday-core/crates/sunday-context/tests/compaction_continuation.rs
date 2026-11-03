//! Does the agent still work *after* compaction, with a real model?
//!
//! The earlier round measured whether the summary contained the right strings.
//! That is a proxy. What actually matters is whether a later step can still do
//! the job with only the compacted transcript, so this file runs that step and
//! checks the answer.
//!
//! Two things are measured:
//!
//!   1. cause retention: does the summary keep *why*, not only *what*
//!   2. task continuation: given the compacted list, can the model answer a
//!      question whose answer depends on a detail only present in the summary
//!
//! Ignored by default because it calls a real provider.

use sunday_context::summary_prompt;
use sunday_context::{compact, estimate_tokens, Policy, Summarizer};
use sunday_llm::{LlmClient, ProviderConfig};
use sunday_protocol::{CoreError, Message, Model, ModelDelta};

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
                    content: summary_prompt::SUMMARISER_SYSTEM_PROMPT.to_owned(),
                },
                Message::User {
                    content: summary_prompt::user_prompt(&transcript),
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
            let mut sink = |_: ModelDelta| {};
            self.client.stream(request, &mut sink).await
        })?;
        turn.text.ok_or_else(|| CoreError::model("no summary text"))
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

fn client() -> LlmClient {
    LlmClient::new(ProviderConfig::openai(base_url(), "test")).expect("client")
}

/// A transcript about a real-ish bug. The information that matters is the
/// *cause*, which is only stated once, buried in tool output.
fn transcript() -> Vec<Message> {
    let mut messages = vec![
        Message::System {
            content: "You are Sunday, a coding agent.".into(),
        },
        Message::User {
            content: "The nightly import loses rows. Fix it, and tell me what caused it.".into(),
        },
    ];
    for step in 0..8 {
        messages.push(Message::Assistant {
            content: format!("step {step}: inspecting the importer"),
        });
        messages.push(Message::ToolResult {
            call_id: format!("c{step}"),
            name: "read_file".into(),
            content: format!(
                "line {}: rows = line.split(',')\n\
                 # The trailing comma makes split produce an empty field, and the \
                 validator then rejects the whole row, so exactly 17 rows vanish per file.",
                10 + step
            ),
        });
    }
    messages.push(Message::Assistant {
        content: "found it: the unconditional split on a trailing comma drops rows".into(),
    });
    messages
}

fn policy() -> Policy {
    Policy {
        trigger_tokens: 1,
        keep_recent: 2,
        max_summary_chars: 1_200,
    }
}

/// Ask the model a question whose answer is only available if the cause survived.
fn ask(client: &LlmClient, compacted: &[Message], question: &str) -> String {
    let mut messages = compacted.to_vec();
    messages.push(Message::User {
        content: question.to_owned(),
    });
    let request = sunday_protocol::ModelRequest {
        model_id: model_id(),
        messages,
        tools: Vec::new(),
        temperature: Some(0.0),
        max_output_tokens: Some(120),
        cancel: Default::default(),
    };
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("runtime");
    let turn = runtime
        .block_on(async {
            let mut sink = |_: ModelDelta| {};
            client.stream(request, &mut sink).await
        })
        .expect("answer");
    turn.text.unwrap_or_default()
}

#[test]
#[ignore = "needs a real summariser"]
fn the_summary_keeps_the_cause_not_only_the_number() {
    let messages = transcript();
    let summarizer = ModelSummarizer {
        client: client(),
        model_id: model_id(),
    };
    let result = compact(&messages, &policy(), &summarizer)
        .expect("compaction")
        .expect("should compact");

    let summary = result
        .messages
        .iter()
        .find_map(|m| match m {
            Message::User { content } if content.contains("Summary of the earlier") => {
                Some(content.clone())
            }
            _ => None,
        })
        .expect("a summary message");
    println!("--- summary ---\n{summary}\n--- end ---");

    let lower = summary.to_lowercase();
    // The cause: a trailing comma feeding an unconditional split.
    let names_cause = lower.contains("comma") || lower.contains("split");
    let names_effect = lower.contains("17") || lower.contains("drop") || lower.contains("vanish");
    assert!(
        names_cause,
        "the summary kept the symptom but lost the cause, which is the failure this prompt change is for:\n{summary}"
    );
    assert!(names_effect, "the summary lost what goes wrong:\n{summary}");
    println!(
        "{} messages -> {} | ~{} -> ~{} tokens",
        messages.len(),
        result.messages.len(),
        estimate_tokens(&messages),
        estimate_tokens(&result.messages)
    );
}

#[test]
#[ignore = "needs a real summariser"]
fn the_agent_can_still_answer_a_cause_question_after_compaction() {
    let messages = transcript();
    let summarizer = ModelSummarizer {
        client: client(),
        model_id: model_id(),
    };
    let result = compact(&messages, &policy(), &summarizer)
        .expect("compaction")
        .expect("should compact");

    let client = client();
    let answer = ask(
        &client,
        &result.messages,
        "In one sentence, what is the root cause of the missing rows? Answer from the \
         conversation above only.",
    );
    println!("--- answer after compaction ---\n{answer}\n--- end ---");

    let lower = answer.to_lowercase();
    // The answer must identify the cause, not merely restate that rows vanish.
    assert!(
        lower.contains("comma") || lower.contains("split"),
        "the agent could not name the cause after compaction, so the task could not continue:\n{answer}"
    );
}

#[test]
#[ignore = "needs a real summariser"]
fn compaction_shrinks_a_long_transcript_materially() {
    let messages = transcript();
    let before = estimate_tokens(&messages);
    let summarizer = ModelSummarizer {
        client: client(),
        model_id: model_id(),
    };
    let result = compact(&messages, &policy(), &summarizer)
        .expect("compaction")
        .expect("should compact");
    let after = estimate_tokens(&result.messages);
    let ratio = before as f64 / after as f64;
    println!(
        "token estimate {before} -> {after} ({ratio:.2}x) over {} messages -> {}",
        messages.len(),
        result.messages.len()
    );

    // A summary that does not shrink anything has no reason to exist, but the
    // bar cannot be "2x": keeping causes costs tokens, and this transcript is
    // short enough that the pinned task plus the summary is a large share of it.
    // Measured with the cause-preserving prompt: 449 -> 213 tokens (2.1x) on the
    // 19 message transcript. The bar here is deliberately below the measurement
    // so a prompt tweak that keeps the cause is not punished, while a summary
    // that barely shrinks anything still fails.
    assert!(
        after < before,
        "compaction grew the transcript: {before} -> {after}"
    );
    assert!(
        ratio >= 1.4,
        "compaction only reached {after} from {before} ({ratio:.2}x), which is not worth the loss of detail"
    );
}

/// A summary must not invent a cause the transcript never states. This is the
/// other half of "keep the cause": a model asked for causes will otherwise
/// produce a plausible one.
#[test]
#[ignore = "needs a real summariser"]
fn the_summary_does_not_invent_a_cause() {
    let mut messages = vec![
        Message::System {
            content: "You are Sunday.".into(),
        },
        Message::User {
            content: "The build fails. Find out why.".into(),
        },
    ];
    for step in 0..8 {
        messages.push(Message::Assistant {
            content: format!("step {step}: reading the build log"),
        });
        messages.push(Message::ToolResult {
            call_id: format!("c{step}"),
            name: "read_file".into(),
            // Deliberately states no cause at all: the log was truncated.
            content: "the log ends mid-line, the compiler output was not captured".into(),
        });
    }
    let summarizer = ModelSummarizer {
        client: client(),
        model_id: model_id(),
    };
    let result = compact(&messages, &policy(), &summarizer)
        .expect("compaction")
        .expect("should compact");
    let summary = result
        .messages
        .iter()
        .filter_map(|m| match m {
            Message::User { content } if content.contains("Summary of the earlier") => {
                Some(content.clone())
            }
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("\n");
    println!("--- summary of an unknown cause ---\n{summary}\n--- end ---");
    let lower = summary.to_lowercase();
    // Naming a specific compiler error that was never seen would be fabrication.
    for invented in [
        "missing semicolon",
        "undefined reference",
        "syntax error",
        "linker error",
    ] {
        assert!(
            !lower.contains(invented),
            "the summary invented a cause the transcript never stated ({invented}):\n{summary}"
        );
    }
}
