//! Context budget and compaction.
//!
//! This crate answers one question: given a message list and a budget, what does
//! the model actually see? It does not decide *when* to compact (the agent does),
//! and it does not talk to a provider itself (a `Summarizer` is injected).
//!
//! Three things must survive compaction, and they survive by construction rather
//! than by care:
//!
//! * pending approvals live in the store, never in the message list
//! * pending user guidance lives in the store, never in the message list
//! * a tool result is never separated from the assistant call that produced it

pub mod summary_prompt;

use sunday_protocol::{CoreError, Message};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Policy {
    /// Compact once the estimate exceeds this.
    pub trigger_tokens: usize,
    /// Always keep this many trailing units verbatim.
    pub keep_recent: usize,
    /// Cap the summary so compaction cannot itself blow the budget.
    pub max_summary_chars: usize,
}

impl Default for Policy {
    fn default() -> Self {
        Self {
            trigger_tokens: 24_000,
            keep_recent: 8,
            max_summary_chars: 4_000,
        }
    }
}

/// Injected so this crate never depends on a provider.
pub trait Summarizer: Send + Sync {
    fn summarize(&self, dropped: &[Message]) -> Result<String, CoreError>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Compaction {
    pub messages: Vec<Message>,
    pub removed_messages: usize,
    pub summary_chars: usize,
}

/// Rough token estimate. Deliberately simple and slightly pessimistic: CJK text
/// is closer to one token per character, latin text closer to one per four.
pub fn estimate_tokens(messages: &[Message]) -> usize {
    messages.iter().map(estimate_one).sum()
}

fn estimate_one(message: &Message) -> usize {
    let text = match message {
        Message::System { content } => content,
        Message::User { content } => content,
        Message::UserMultimodal { content, images } => {
            // An image costs roughly a thousand tokens; count it as such.
            return estimate_text(content) + images.len() * 1_000;
        }
        Message::Assistant { content } => content,
        Message::AssistantToolCalls { calls, content } => {
            let args: usize = calls
                .iter()
                .map(|c| c.args.to_string().chars().count() / 3 + c.name.chars().count())
                .sum();
            return estimate_text(content.as_deref().unwrap_or("")) + args;
        }
        Message::ToolResult { content, .. } => content,
    };
    estimate_text(text)
}

fn estimate_text(text: &str) -> usize {
    let chars = text.chars().count();
    let wide = text.chars().filter(|c| (*c as u32) > 0x2E80).count();
    // Wide characters count as one token, the rest as a quarter.
    wide + (chars - wide).div_ceil(4)
}

pub fn needs_compaction(messages: &[Message], policy: &Policy) -> bool {
    estimate_tokens(messages) > policy.trigger_tokens
}

/// Splits messages into units that must be kept or dropped together: an
/// assistant tool-call message is always attached to the results that follow it.
fn units(messages: &[Message]) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut index = 0;
    while index < messages.len() {
        let start = index;
        index += 1;
        if matches!(messages[start], Message::AssistantToolCalls { .. }) {
            while index < messages.len() && matches!(messages[index], Message::ToolResult { .. }) {
                index += 1;
            }
        }
        out.push((start, index));
    }
    out
}

/// Compacts when over budget. Returns `None` when nothing needs to happen, so a
/// caller cannot mistake "compacted to the same thing" for real work.
pub fn compact(
    messages: &[Message],
    policy: &Policy,
    summarizer: &dyn Summarizer,
) -> Result<Option<Compaction>, CoreError> {
    if !needs_compaction(messages, policy) {
        return Ok(None);
    }

    let units = units(messages);
    if units.len() <= 1 {
        return Ok(None);
    }

    // Pin the system prompt and the task statement. Summarising the task away is
    // how an agent forgets what it was asked to do, so neither is droppable.
    let mut first_movable_unit = 0usize;
    if matches!(messages[units[0].0], Message::System { .. }) {
        first_movable_unit = 1;
    }
    if let Some((start, _)) = units.get(first_movable_unit) {
        if matches!(
            messages[*start],
            Message::User { .. } | Message::UserMultimodal { .. }
        ) {
            first_movable_unit += 1;
        }
    }

    let keep_units = policy.keep_recent.max(1);
    let mut keep_from_unit = units
        .len()
        .saturating_sub(keep_units)
        .max(first_movable_unit);

    // A newer user instruction must not be summarised away: if it sits before the
    // kept tail but is still droppable, pull the tail back to include it.
    if let Some(last_user) = messages
        .iter()
        .rposition(|m| matches!(m, Message::User { .. } | Message::UserMultimodal { .. }))
    {
        if let Some(target) = units
            .iter()
            .position(|(start, end)| *start <= last_user && last_user < *end)
        {
            if target >= first_movable_unit && target < keep_from_unit {
                keep_from_unit = target;
            }
        }
    }

    if keep_from_unit <= first_movable_unit {
        return Ok(None);
    }

    let drop_start = units[first_movable_unit].0;
    let drop_end = units[keep_from_unit].0;
    if drop_end <= drop_start {
        return Ok(None);
    }

    let dropped = &messages[drop_start..drop_end];
    let mut summary = summarizer.summarize(dropped)?;
    if summary.chars().count() > policy.max_summary_chars {
        summary = summary.chars().take(policy.max_summary_chars).collect();
    }

    let mut out = Vec::with_capacity(messages.len() - dropped.len() + 1);
    out.extend_from_slice(&messages[..drop_start]);
    // A user-role context message, not a second system message: some providers
    // only accept a system prompt at the very top, and the pinned task already
    // occupies that position.
    out.push(Message::User {
        content: format!("Summary of the earlier conversation:\n{summary}"),
    });
    out.extend_from_slice(&messages[drop_end..]);

    Ok(Some(Compaction {
        messages: out,
        removed_messages: dropped.len(),
        summary_chars: summary.chars().count(),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fixed(String);
    impl Summarizer for Fixed {
        fn summarize(&self, _dropped: &[Message]) -> Result<String, CoreError> {
            Ok(self.0.clone())
        }
    }

    struct Failing;
    impl Summarizer for Failing {
        fn summarize(&self, _dropped: &[Message]) -> Result<String, CoreError> {
            Err(CoreError::model("summarizer unavailable"))
        }
    }

    fn user(text: &str) -> Message {
        Message::User {
            content: text.into(),
        }
    }

    fn system(text: &str) -> Message {
        Message::System {
            content: text.into(),
        }
    }

    fn call(id: &str) -> Message {
        Message::AssistantToolCalls {
            calls: vec![sunday_protocol::ToolCall {
                id: id.into(),
                name: "write_file".into(),
                args: serde_json::json!({"path": "a.txt"}),
            }],
            content: None,
        }
    }

    fn result(id: &str) -> Message {
        Message::ToolResult {
            call_id: id.into(),
            name: "write_file".into(),
            content: "ok".into(),
        }
    }

    fn policy(trigger: usize, keep: usize) -> Policy {
        Policy {
            trigger_tokens: trigger,
            keep_recent: keep,
            max_summary_chars: 100,
        }
    }

    #[test]
    fn under_budget_means_no_work() {
        let messages = vec![system("s"), user("hi")];
        assert!(compact(&messages, &policy(10_000, 4), &Fixed("x".into()))
            .unwrap()
            .is_none());
    }

    #[test]
    fn compaction_keeps_the_system_prompt_and_the_tail() {
        let mut messages = vec![system("You are Sunday.")];
        for index in 0..40 {
            messages.push(user(&format!("message number {index} with some length")));
        }
        let out = compact(&messages, &policy(100, 4), &Fixed("earlier chatter".into()))
            .unwrap()
            .expect("compaction should run");

        assert_eq!(out.messages[0], system("You are Sunday."));
        // The first user message is the task statement and stays pinned.
        assert!(matches!(out.messages[1], Message::User { .. }));
        assert!(matches!(out.messages[2], Message::User { .. }));
        assert!(out.messages[2].to_string_contains("Summary of the earlier conversation"));
        // The tail is intact and ordered.
        let tail = &out.messages[out.messages.len() - 3..];
        assert!(matches!(tail[0], Message::User { .. }));
        assert!(matches!(tail[2], Message::User { .. }));
    }

    #[test]
    fn a_tool_call_is_never_separated_from_its_result() {
        let mut messages = vec![system("s")];
        for index in 0..10 {
            messages.push(user(&format!("step {index}")));
            messages.push(call(&format!("c{index}")));
            messages.push(result(&format!("c{index}")));
        }
        let out = compact(&messages, &policy(50, 2), &Fixed("x".into()))
            .unwrap()
            .unwrap();

        // Every assistant tool-call message must be followed by its results.
        for (index, message) in out.messages.iter().enumerate() {
            if let Message::AssistantToolCalls { calls, .. } = message {
                let next = out.messages.get(index + 1).expect("result must follow");
                match next {
                    Message::ToolResult { call_id, .. } => {
                        assert_eq!(call_id, &calls[0].id, "result belongs to a different call")
                    }
                    other => panic!("tool call followed by {other:?}"),
                }
            }
        }
    }

    #[test]
    fn the_last_user_instruction_is_never_dropped() {
        let mut messages = vec![system("s")];
        for index in 0..30 {
            messages.push(user(&format!("older {index}")));
            messages.push(call(&format!("c{index}")));
            messages.push(result(&format!("c{index}")));
        }
        let last = user("the instruction that matters");
        messages.push(last.clone());

        let out = compact(&messages, &policy(50, 1), &Fixed("x".into()))
            .unwrap()
            .unwrap();
        assert!(
            out.messages.contains(&last),
            "the newest instruction must survive"
        );
        assert_eq!(out.messages.last(), Some(&last));
    }

    #[test]
    fn a_failing_summarizer_surfaces_instead_of_silently_dropping() {
        let mut messages = vec![system("s")];
        for index in 0..20 {
            messages.push(user(&format!("m{index}")));
        }
        let err = compact(&messages, &policy(10, 2), &Failing).unwrap_err();
        assert!(matches!(err, CoreError::Model { .. }), "got {err:?}");
    }

    #[test]
    fn the_summary_is_capped() {
        let mut messages = vec![system("s")];
        for index in 0..20 {
            messages.push(user(&format!("m{index}")));
        }
        let out = compact(&messages, &policy(10, 2), &Fixed("y".repeat(10_000)))
            .unwrap()
            .unwrap();
        assert_eq!(out.summary_chars, 100);
    }

    #[test]
    fn estimate_grows_with_content() {
        let short = vec![user("hi")];
        let long = vec![user(&"x".repeat(400))];
        assert!(estimate_tokens(&long) > estimate_tokens(&short));
    }

    trait Contains {
        fn to_string_contains(&self, needle: &str) -> bool;
    }
    impl Contains for Message {
        fn to_string_contains(&self, needle: &str) -> bool {
            match self {
                Message::System { content } | Message::User { content } => content.contains(needle),
                _ => false,
            }
        }
    }
}
