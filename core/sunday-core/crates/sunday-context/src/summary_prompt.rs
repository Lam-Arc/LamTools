//! The prompt used to compress a transcript.
//!
//! This lives here, beside `compact`, because it *is* part of the compaction
//! policy. When it lived only in a host (and, before that, only in a test), the
//! policy drifted: the code kept the mechanism and lost the quality bar.
//!
//! The earlier prompt said "keep every fact a later step could still need".
//! Measured against a real model that produced summaries which kept the number
//! from a bug report but dropped the cause, so a later step knew *what* was
//! wrong and not *why*. That is worse than useless: it invites a confident,
//! wrong fix. The prompt below asks for cause explicitly and names the failure.

/// What the summariser is told to do.
///
/// Held as a constant so a test can assert the requirements are actually in the
/// prompt instead of trusting that they were edited in.
pub const SUMMARISER_SYSTEM_PROMPT: &str = "\
You compress a conversation transcript so an agent can continue the task without \
re-reading it.

Keep, in this order of importance:

1. WHY. Every cause, reason and constraint. If something was changed or ruled out, \
say why. A cause is worth more than the number it produced.
2. WHAT IS STILL OPEN. Unfinished work, open questions, decisions still pending.
3. EXACT VALUES that a later step must reuse: file paths, identifiers, error \
messages, counts, limits, deadlines. Copy them verbatim.

Drop: greetings, restatements, repeated tool output, and any reasoning that did \
not end in a decision.

Rules:
- Never invent a cause that the transcript does not state.
- Never merge two separate problems into one sentence.
- Write plainly. No preamble, no headings, no bullet points.
";

/// Asked of a specific chunk, so the model knows what it is looking at.
pub fn user_prompt(transcript: &str) -> String {
    format!(
        "Summarise this part of the transcript. Keep causes and open work; copy \
         exact values verbatim.\n\n---\n{transcript}\n---"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_prompt_asks_for_causes_not_only_facts() {
        let prompt = SUMMARISER_SYSTEM_PROMPT.to_lowercase();
        assert!(
            prompt.contains("why"),
            "the prompt no longer asks for causes, which is the exact regression this file guards"
        );
        assert!(
            prompt.contains("cause"),
            "the prompt does not mention causes"
        );
        assert!(
            prompt.contains("never invent"),
            "the prompt does not forbid inventing a cause, which a model under pressure will do"
        );
    }

    #[test]
    fn the_prompt_keeps_exact_values() {
        let prompt = SUMMARISER_SYSTEM_PROMPT.to_lowercase();
        assert!(prompt.contains("paths"), "file paths are not mentioned");
        assert!(
            prompt.contains("verbatim"),
            "the prompt does not ask for exact values to be copied"
        );
    }

    #[test]
    fn the_user_prompt_carries_the_transcript() {
        let prompt = user_prompt("user: the parser drops 17 rows because of a trailing comma");
        assert!(prompt.contains("17 rows"));
        assert!(prompt.contains("trailing comma"));
    }
}
