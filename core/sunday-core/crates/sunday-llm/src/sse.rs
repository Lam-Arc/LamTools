//! Incremental server-sent-events parser.
//!
//! The old provider parsed SSE inside the same file as transport and four wire
//! formats. Here it is its own unit with its own tests, because frame
//! boundaries are where streaming code actually breaks.

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SseEvent {
    pub event: String,
    pub data: String,
}

#[derive(Default)]
pub struct SseParser {
    buffer: String,
    event: String,
    data: String,
    /// Bytes consumed so far, for diagnostics.
    pub consumed: usize,
}

impl SseParser {
    pub fn new() -> Self {
        Self::default()
    }

    /// Feed an arbitrary chunk. Yields every event that completed in this chunk.
    /// A chunk may end mid-line, mid-field, or exactly between events.
    pub fn push(&mut self, chunk: &str) -> Vec<SseEvent> {
        self.buffer.push_str(chunk);
        self.consumed += chunk.len();
        let mut out = Vec::new();
        while let Some(newline) = self.buffer.find('\n') {
            let line: String = self.buffer.drain(..=newline).collect();
            let line = line.trim_end_matches('\n').trim_end_matches('\r');
            if line.is_empty() {
                if !self.data.is_empty() || !self.event.is_empty() {
                    out.push(SseEvent {
                        event: std::mem::take(&mut self.event),
                        data: std::mem::take(&mut self.data),
                    });
                }
                continue;
            }
            if let Some(rest) = line.strip_prefix("event:") {
                self.event = rest.trim().to_owned();
            } else if let Some(rest) = line.strip_prefix("data:") {
                if !self.data.is_empty() {
                    self.data.push('\n');
                }
                self.data.push_str(rest.strip_prefix(' ').unwrap_or(rest));
            }
            // id:, retry:, and comments (:) are ignored on purpose.
        }
        out
    }

    /// Flush a trailing line and event that were not terminated by a newline.
    pub fn finish(&mut self) -> Option<SseEvent> {
        if !self.buffer.is_empty() {
            let line = std::mem::take(&mut self.buffer);
            let line = line.trim_end_matches('\n').trim_end_matches('\r');
            if let Some(rest) = line.strip_prefix("event:") {
                self.event = rest.trim().to_owned();
            } else if let Some(rest) = line.strip_prefix("data:") {
                if !self.data.is_empty() {
                    self.data.push('\n');
                }
                self.data.push_str(rest.strip_prefix(' ').unwrap_or(rest));
            }
        }
        if self.data.is_empty() && self.event.is_empty() {
            return None;
        }
        Some(SseEvent {
            event: std::mem::take(&mut self.event),
            data: std::mem::take(&mut self.data),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_whole_events() {
        let mut p = SseParser::new();
        let events = p.push("data: {\"a\":1}\n\ndata: {\"b\":2}\n\n");
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].data, "{\"a\":1}");
        assert_eq!(events[1].data, "{\"b\":2}");
    }

    #[test]
    fn survives_a_split_in_the_middle_of_a_field() {
        let mut p = SseParser::new();
        assert!(p.push("da").is_empty());
        assert!(p.push("ta: {\"a\"").is_empty());
        let events = p.push(":1}\n\n");
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].data, "{\"a\":1}");
    }

    #[test]
    fn survives_a_split_between_events() {
        let mut p = SseParser::new();
        assert_eq!(p.push("data: x\n\n").len(), 1);
        assert!(p.push("data: y").is_empty());
        let events = p.push("\n\n");
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].data, "y");
    }

    #[test]
    fn carriage_returns_do_not_leak_into_data() {
        let mut p = SseParser::new();
        let events = p.push("data: hello\r\n\r\n");
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].data, "hello");
    }

    #[test]
    fn named_events_are_captured() {
        let mut p = SseParser::new();
        let events = p.push("event: content_block_delta\ndata: {}\n\n");
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].event, "content_block_delta");
    }

    #[test]
    fn multi_line_data_is_joined() {
        let mut p = SseParser::new();
        let events = p.push("data: line1\ndata: line2\n\n");
        assert_eq!(events[0].data, "line1\nline2");
    }

    #[test]
    fn unterminated_tail_can_be_flushed() {
        let mut p = SseParser::new();
        assert!(p.push("data: tail").is_empty());
        assert_eq!(p.finish().unwrap().data, "tail");
        assert!(p.finish().is_none());
    }
}
