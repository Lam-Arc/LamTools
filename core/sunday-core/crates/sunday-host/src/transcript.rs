//! The conversation the model has already had, rebuilt from the journal.
//!
//! user:“Rust Core和 Python Core 等价吗？可以安全切换吗”+(先补最要命的一处：Python 每轮都把
//! 历史消息放进模型请求，Rust 侧原来只发一条 user，等于单轮问答)。
//!
//! The journal is the only durable record of a turn, so the transcript is derived from it
//: there is no second store to drift out of step with what actually happened. A tool call
//! is only ever reconstructed from the same events that recorded its dispatch and outcome,
//! so a message the model sees here is a message that ran.
//!
//! Deliberately not replayed: approvals (they are a gate, not a thing the model said),
//! run lifecycle markers, and replays of a result that is already in the list.

use sunday_protocol::{Event, EventKind, Message};

/// How many journal events one transcript may read.
///
/// A thread that has run for months is still readable in bounded time; a turn older than
/// this is context the model would have been compacted past anyway.
pub const MAX_EVENTS: usize = 4000;

/// Rebuilds the messages a turn should start from.
///
/// The events must be in journal order. Tool calls are grouped back into the assistant
/// message that issued them, because a provider rejects a tool result that does not follow
/// its call.
pub fn messages(events: &[Event]) -> Vec<Message> {
    let mut out: Vec<Message> = Vec::new();
    // Calls whose results have not arrived yet, in the order the model asked for them.
    let mut pending: Vec<sunday_protocol::ToolCall> = Vec::new();

    for event in events {
        match event.kind {
            EventKind::CommandAccepted => {
                let kind = event.payload.get("kind").and_then(|value| value.as_str());
                if kind != Some("turn_start") {
                    continue;
                }
                let text = event
                    .payload
                    .get("text")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default();
                if text.trim().is_empty() {
                    continue;
                }
                out.push(Message::User {
                    content: text.to_owned(),
                });
            }
            EventKind::GuidanceReceived => {
                let text = event
                    .payload
                    .get("text")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default();
                if text.trim().is_empty() {
                    continue;
                }
                // What the user said mid-turn is the user talking, not the assistant.
                out.push(Message::User {
                    content: text.to_owned(),
                });
            }
            EventKind::ModelCompleted => {
                let text = event
                    .payload
                    .get("text")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default();
                if text.trim().is_empty() {
                    continue;
                }
                out.push(Message::Assistant {
                    content: text.to_owned(),
                });
            }
            EventKind::ToolPrepared => {
                let Some(name) = event.payload.get("name").and_then(|value| value.as_str()) else {
                    continue;
                };
                let id = event
                    .payload
                    .get("tool_call_id")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default()
                    .to_owned();
                let args = event
                    .payload
                    .get("arguments")
                    .cloned()
                    .unwrap_or(serde_json::Value::Null);
                pending.push(sunday_protocol::ToolCall {
                    id,
                    name: name.to_owned(),
                    args,
                });
            }
            EventKind::ToolSucceeded | EventKind::ToolFailed | EventKind::ToolOutcomeUnknown => {
                flush(&mut pending, &mut out);
                let name = event
                    .payload
                    .get("name")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default()
                    .to_owned();
                let call_id = event
                    .payload
                    .get("tool_call_id")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default()
                    .to_owned();
                let content = match event.kind {
                    EventKind::ToolSucceeded => event
                        .payload
                        .get("content")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default()
                        .to_owned(),
                    EventKind::ToolFailed => event
                        .payload
                        .get("error")
                        .and_then(|value| value.as_str())
                        .unwrap_or_default()
                        .to_owned(),
                    // The one case the journal cannot answer. Saying so is better than
                    // dropping it: the model must not believe the call quietly succeeded.
                    _ => "（这次工具调用的结果未知：进程在它返回之前结束了。）".to_owned(),
                };
                out.push(Message::ToolResult {
                    call_id,
                    name,
                    content,
                });
            }
            // A replay re-reports an outcome that is already in the list above it.
            EventKind::ToolReplayed
            | EventKind::ToolDispatched
            | EventKind::ApprovalRequested
            | EventKind::ApprovalResolved
            | EventKind::RunStarted
            | EventKind::RunCompleted
            | EventKind::RunCancelled
            | EventKind::RunWaitingForReconciliation
            | EventKind::ModelStarted
            | EventKind::ContextCompacted => {}
        }
    }
    // A call whose result never arrived still has to be paired, or the next request is
    // invalid: providers reject an assistant tool call with no answer.
    flush(&mut pending, &mut out);
    out
}

/// Emits the assistant message that issued the buffered calls.
fn flush(pending: &mut Vec<sunday_protocol::ToolCall>, out: &mut Vec<Message>) {
    if pending.is_empty() {
        return;
    }
    out.push(Message::AssistantToolCalls {
        calls: std::mem::take(pending),
        content: None,
    });
}

/// Drops the middle of a long conversation without inventing what it said.
///
/// A model-written summary would cost a model call before every compacted turn and can
/// introduce facts that were never there. This says exactly what happened instead; when
/// the details matter the user can repeat them.
pub struct OmittedNote;

impl sunday_context::Summarizer for OmittedNote {
    fn summarize(&self, dropped: &[Message]) -> Result<String, sunday_protocol::CoreError> {
        Ok(format!(
            "（更早的 {} 条消息因为超出上下文预算已省略。需要其中的细节时请让用户重述。）",
            dropped.len()
        ))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn event(kind: EventKind, payload: serde_json::Value) -> Event {
        Event {
            thread_id: "th".into(),
            seq: 0,
            event_id: String::new(),
            kind,
            payload,
            created_at: 0,
        }
    }

    fn accepted(text: &str) -> Event {
        event(
            EventKind::CommandAccepted,
            json!({ "kind": "turn_start", "text": text }),
        )
    }

    #[test]
    fn a_turn_becomes_a_user_message() {
        let messages = messages(&[accepted("hello")]);
        assert_eq!(
            messages,
            vec![Message::User {
                content: "hello".into()
            }]
        );
    }

    /// Two turns must be two user messages with the answer between them.
    #[test]
    fn two_turns_keep_their_order() {
        let messages = messages(&[
            accepted("first"),
            event(EventKind::ModelCompleted, json!({ "text": "one" })),
            accepted("second"),
            event(EventKind::ModelCompleted, json!({ "text": "two" })),
        ]);
        assert_eq!(messages.len(), 4);
        assert_eq!(
            messages[2],
            Message::User {
                content: "second".into()
            }
        );
        assert_eq!(
            messages[3],
            Message::Assistant {
                content: "two".into()
            }
        );
    }

    /// A tool call and its result must stay adjacent and in that order.
    #[test]
    fn a_tool_call_is_paired_with_its_result() {
        let messages = messages(&[
            accepted("write it"),
            event(
                EventKind::ToolPrepared,
                json!({ "tool_call_id": "c1", "name": "write_file", "arguments": { "path": "a" } }),
            ),
            event(
                EventKind::ToolSucceeded,
                json!({ "tool_call_id": "c1", "name": "write_file", "content": "ok" }),
            ),
        ]);
        assert_eq!(messages.len(), 3, "{messages:?}");
        match &messages[1] {
            Message::AssistantToolCalls { calls, .. } => {
                assert_eq!(calls.len(), 1);
                assert_eq!(calls[0].name, "write_file");
            }
            other => panic!("expected the call before its result, got {other:?}"),
        }
        assert_eq!(
            messages[2],
            Message::ToolResult {
                call_id: "c1".into(),
                name: "write_file".into(),
                content: "ok".into()
            }
        );
    }

    /// A failure is a result too, and carries the reason.
    #[test]
    fn a_failed_tool_keeps_its_reason() {
        let messages = messages(&[
            event(
                EventKind::ToolPrepared,
                json!({ "tool_call_id": "c1", "name": "read_file", "arguments": {} }),
            ),
            event(
                EventKind::ToolFailed,
                json!({ "tool_call_id": "c1", "name": "read_file", "error": "no such file" }),
            ),
        ]);
        match messages.last() {
            Some(Message::ToolResult { content, .. }) => assert_eq!(content, "no such file"),
            other => panic!("expected a result, got {other:?}"),
        }
    }

    /// An unknown outcome must not look like success, and must not vanish.
    #[test]
    fn an_unknown_outcome_is_reported_as_unknown() {
        let messages = messages(&[
            event(
                EventKind::ToolPrepared,
                json!({ "tool_call_id": "c1", "name": "write_file", "arguments": {} }),
            ),
            event(
                EventKind::ToolOutcomeUnknown,
                json!({ "tool_call_id": "c1", "name": "write_file" }),
            ),
        ]);
        match messages.last() {
            Some(Message::ToolResult { content, .. }) => {
                assert!(content.contains("结果未知"), "{content}")
            }
            other => panic!("expected a result, got {other:?}"),
        }
    }

    /// Guidance is the user talking, so it is a user message.
    #[test]
    fn guidance_is_a_user_message() {
        let messages = messages(&[event(
            EventKind::GuidanceReceived,
            json!({ "guidance_id": "g1", "text": "先别删那个文件" }),
        )]);
        assert_eq!(
            messages,
            vec![Message::User {
                content: "先别删那个文件".into()
            }]
        );
    }

    /// A call with no result still gets its assistant message, so the next request is
    /// valid; the missing answer is simply not there.
    #[test]
    fn a_call_without_a_result_is_still_paired() {
        let messages = messages(&[event(
            EventKind::ToolPrepared,
            json!({ "tool_call_id": "c1", "name": "write_file", "arguments": {} }),
        )]);
        assert!(matches!(
            messages.as_slice(),
            [Message::AssistantToolCalls { .. }]
        ));
    }

    #[test]
    fn lifecycle_noise_is_not_context() {
        let messages = messages(&[
            event(EventKind::RunStarted, json!({ "turn_id": "t" })),
            accepted("hi"),
            event(EventKind::ModelStarted, json!({ "round": 0 })),
            event(EventKind::RunCompleted, json!({ "text": "" })),
        ]);
        assert_eq!(messages.len(), 1, "{messages:?}");
    }
}
