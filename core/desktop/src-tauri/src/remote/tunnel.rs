use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// The serialized JSON-line envelope remains small enough to traverse a
/// browser/native WebSocket comfortably. Large logical payloads are split
/// below this boundary and reassembled by `TunnelStreamDecoder`.
pub const MAX_FRAME_PAYLOAD_BYTES: usize = 4 * 1024 * 1024;
pub const MAX_MESSAGE_PAYLOAD_BYTES: usize = 128 * 1024 * 1024;
pub const MAX_CHUNK_PAYLOAD_CHARS: usize = 256 * 1024;
const MAX_INFLIGHT_MESSAGES: usize = 16;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub struct TunnelFrame {
    pub version: u8,
    #[serde(rename = "type")]
    pub frame_type: String,
    pub stream_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub payload: Option<String>,
    /// Present only when one logical frame is split across several tunnel
    /// frames. Sequence numbers still provide the replay/order guard.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chunk_index: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chunk_final: Option<bool>,
    pub sequence: u64,
}

impl TunnelFrame {
    pub fn new(frame_type: impl Into<String>, stream_id: impl Into<String>, sequence: u64) -> Self {
        Self {
            version: 1,
            frame_type: frame_type.into(),
            stream_id: stream_id.into(),
            request_id: None,
            payload: None,
            message_id: None,
            chunk_index: None,
            chunk_final: None,
            sequence,
        }
    }
}

#[derive(Default, Debug)]
pub struct TunnelCodec {
    last_sequence: u64,
}

#[derive(Default, Debug)]
pub struct TunnelStreamDecoder {
    codec: TunnelCodec,
    buffer: Vec<u8>,
    partials: HashMap<String, PartialTunnelFrame>,
}

#[derive(Debug)]
struct PartialTunnelFrame {
    frame: TunnelFrame,
    next_chunk_index: u32,
    payload_bytes: usize,
}

impl TunnelStreamDecoder {
    pub fn push(&mut self, chunk: &[u8]) -> Result<Vec<TunnelFrame>, String> {
        self.buffer.extend_from_slice(chunk);
        let mut frames = Vec::new();
        let mut consumed = 0;
        while let Some(relative_end) = self.buffer[consumed..]
            .iter()
            .position(|byte| *byte == b'\n')
        {
            let end = consumed + relative_end;
            if end.saturating_sub(consumed) > MAX_FRAME_PAYLOAD_BYTES {
                return Err("tunnel frame is too large".to_string());
            }
            let line = &self.buffer[consumed..end];
            consumed = end + 1;
            if line.is_empty() {
                continue;
            }
            let decoded = self.codec.decode_line(line)?;
            if let Some(frame) = self.push_frame(decoded)? {
                frames.push(frame);
            }
        }
        if consumed > 0 {
            self.buffer.drain(..consumed);
        }
        // The limit applies to the incomplete frame only. A single network
        // read may legally contain many complete frames whose combined size
        // is larger than the per-frame limit.
        if self.buffer.len() > MAX_FRAME_PAYLOAD_BYTES {
            return Err("tunnel frame is too large".to_string());
        }
        Ok(frames)
    }

    fn push_frame(&mut self, frame: TunnelFrame) -> Result<Option<TunnelFrame>, String> {
        let Some(message_id) = frame.message_id.clone() else {
            if frame.chunk_index.is_some() || frame.chunk_final.is_some() {
                return Err("invalid tunnel chunk metadata".to_string());
            }
            return Ok(Some(frame));
        };
        let Some(chunk_index) = frame.chunk_index else {
            return Err("tunnel chunk index is missing".to_string());
        };
        let Some(chunk_final) = frame.chunk_final else {
            return Err("tunnel chunk final marker is missing".to_string());
        };
        let payload = frame
            .payload
            .as_deref()
            .ok_or_else(|| "tunnel chunk payload is missing".to_string())?;
        if chunk_index == 0 {
            if self.partials.len() >= MAX_INFLIGHT_MESSAGES {
                return Err("too many in-flight tunnel messages".to_string());
            }
            if self.partials.contains_key(&message_id) {
                return Err("duplicate tunnel chunk message".to_string());
            }
            let payload_bytes = payload.len();
            if payload_bytes > MAX_MESSAGE_PAYLOAD_BYTES {
                return Err("tunnel message is too large".to_string());
            }
            if chunk_final {
                let mut complete = frame;
                complete.message_id = None;
                complete.chunk_index = None;
                complete.chunk_final = None;
                return Ok(Some(complete));
            }
            let mut partial_frame = frame;
            partial_frame.message_id = None;
            partial_frame.chunk_index = None;
            partial_frame.chunk_final = None;
            self.partials.insert(
                message_id,
                PartialTunnelFrame {
                    frame: partial_frame,
                    next_chunk_index: 1,
                    payload_bytes,
                },
            );
            return Ok(None);
        }

        let partial = self
            .partials
            .get_mut(&message_id)
            .ok_or_else(|| "tunnel chunk sequence started out of order".to_string())?;
        if chunk_index != partial.next_chunk_index {
            return Err("tunnel chunk sequence is invalid".to_string());
        }
        partial.payload_bytes = partial
            .payload_bytes
            .checked_add(payload.len())
            .filter(|size| *size <= MAX_MESSAGE_PAYLOAD_BYTES)
            .ok_or_else(|| "tunnel message is too large".to_string())?;
        partial.next_chunk_index = partial
            .next_chunk_index
            .checked_add(1)
            .ok_or_else(|| "tunnel chunk sequence is invalid".to_string())?;
        partial
            .frame
            .payload
            .get_or_insert_with(String::new)
            .push_str(payload);
        if !chunk_final {
            return Ok(None);
        }
        let completed = self
            .partials
            .remove(&message_id)
            .ok_or_else(|| "tunnel chunk state disappeared".to_string())?;
        Ok(Some(completed.frame))
    }

    pub fn last_sequence(&self) -> u64 {
        self.codec.last_sequence()
    }

    pub fn reset(&mut self) {
        self.buffer.clear();
        self.codec = TunnelCodec::default();
        self.partials.clear();
    }
}

impl TunnelCodec {
    pub fn encode(frame: &TunnelFrame) -> Result<Vec<u8>, String> {
        validate_frame(frame)?;
        let encoded = serde_json::to_vec(frame).map_err(|error| error.to_string())?;
        if encoded.len() > MAX_FRAME_PAYLOAD_BYTES {
            return Err("tunnel frame is too large".to_string());
        }
        let mut line = encoded;
        line.push(b'\n');
        Ok(line)
    }

    pub fn decode_line(&mut self, line: &[u8]) -> Result<TunnelFrame, String> {
        if line.len() > MAX_FRAME_PAYLOAD_BYTES {
            return Err("tunnel frame is too large".to_string());
        }
        let frame: TunnelFrame = serde_json::from_slice(line).map_err(|error| error.to_string())?;
        validate_frame(&frame)?;
        if frame.sequence <= self.last_sequence {
            return Err("tunnel frame sequence replay".to_string());
        }
        self.last_sequence = frame.sequence;
        Ok(frame)
    }

    pub fn last_sequence(&self) -> u64 {
        self.last_sequence
    }
}

fn validate_frame(frame: &TunnelFrame) -> Result<(), String> {
    if frame.version != 1
        || frame.frame_type.trim().is_empty()
        || frame.frame_type.len() > 64
        || frame.stream_id.trim().is_empty()
        || frame.stream_id.len() > 256
        || frame.sequence == 0
        || frame
            .request_id
            .as_ref()
            .is_some_and(|value| value.is_empty() || value.len() > 256)
        || frame
            .message_id
            .as_ref()
            .is_some_and(|value| value.is_empty() || value.len() > 256)
    {
        return Err("invalid tunnel frame".to_string());
    }
    let has_message_id = frame.message_id.is_some();
    if has_message_id != frame.chunk_index.is_some()
        || has_message_id != frame.chunk_final.is_some()
    {
        return Err("invalid tunnel chunk metadata".to_string());
    }
    if frame.chunk_index.is_some_and(|index| index > 524_288) {
        return Err("invalid tunnel chunk index".to_string());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{
        TunnelCodec, TunnelFrame, TunnelStreamDecoder, MAX_CHUNK_PAYLOAD_CHARS,
        MAX_FRAME_PAYLOAD_BYTES,
    };

    #[test]
    fn codec_round_trip_and_replay_guard() {
        let frame = TunnelFrame::new("ping", "control", 1);
        let encoded = TunnelCodec::encode(&frame).expect("encode");
        let mut codec = TunnelCodec::default();
        assert_eq!(
            codec
                .decode_line(&encoded[..encoded.len() - 1])
                .expect("decode"),
            frame
        );
        assert!(codec.decode_line(&encoded[..encoded.len() - 1]).is_err());
    }

    #[test]
    fn stream_decoder_handles_partial_and_coalesced_utf8_frames() {
        let mut first = TunnelFrame::new("rpc.data", "rpc", 1);
        first.payload = Some("你好，LamTools".to_string());
        let mut second = TunnelFrame::new("rpc.data", "rpc", 2);
        second.payload = Some("完成".to_string());
        let first_bytes = TunnelCodec::encode(&first).expect("encode first");
        let second_bytes = TunnelCodec::encode(&second).expect("encode second");
        let split = first_bytes.len() - 4;
        let mut decoder = TunnelStreamDecoder::default();
        assert!(decoder
            .push(&first_bytes[..split])
            .expect("partial")
            .is_empty());
        let mut remainder = first_bytes[split..].to_vec();
        remainder.extend_from_slice(&second_bytes);
        assert_eq!(
            decoder.push(&remainder).expect("remaining"),
            vec![first, second]
        );
        assert_eq!(decoder.last_sequence(), 2);
        decoder.reset();
        assert_eq!(decoder.last_sequence(), 0);
    }

    #[test]
    fn stream_decoder_limits_each_frame_not_the_whole_network_read() {
        let mut first = TunnelFrame::new("event.data", "event", 1);
        first.payload = Some("x".repeat(2_100_000));
        let mut second = TunnelFrame::new("event.data", "event", 2);
        second.payload = Some("y".repeat(2_100_000));
        let first_bytes = TunnelCodec::encode(&first).expect("first fits");
        let second_bytes = TunnelCodec::encode(&second).expect("second fits");
        assert!(first_bytes.len() < MAX_FRAME_PAYLOAD_BYTES);
        assert!(second_bytes.len() < MAX_FRAME_PAYLOAD_BYTES);
        assert!(first_bytes.len() + second_bytes.len() > MAX_FRAME_PAYLOAD_BYTES);

        let mut batch = first_bytes;
        batch.extend_from_slice(&second_bytes);
        let frames = TunnelStreamDecoder::default()
            .push(&batch)
            .expect("coalesced frames");
        assert_eq!(frames, vec![first, second]);
    }

    #[test]
    fn codec_rejects_invalid_frame_fields() {
        let mut version = TunnelFrame::new("rpc.data", "rpc", 1);
        version.version = 2;
        assert!(TunnelCodec::encode(&version).is_err());

        let zero = TunnelFrame::new("rpc.data", "rpc", 0);
        assert!(TunnelCodec::encode(&zero).is_err());

        let long_type = TunnelFrame::new("x".repeat(65), "rpc", 1);
        assert!(TunnelCodec::encode(&long_type).is_err());

        let long_stream = TunnelFrame::new("rpc.data", "x".repeat(257), 1);
        assert!(TunnelCodec::encode(&long_stream).is_err());
    }

    #[test]
    fn stream_decoder_reassembles_large_logical_payload() {
        let payload = "你好".repeat(MAX_CHUNK_PAYLOAD_CHARS / 2 + 17);
        let mut characters = payload.chars();
        let first_payload: String = characters.by_ref().take(MAX_CHUNK_PAYLOAD_CHARS).collect();
        let second_payload: String = characters.collect();
        let mut first = TunnelFrame::new("rpc.data", "rpc", 1);
        first.payload = Some(first_payload);
        first.message_id = Some("message-1".to_string());
        first.chunk_index = Some(0);
        first.chunk_final = Some(false);
        let mut second = TunnelFrame::new("rpc.data", "rpc", 2);
        second.payload = Some(second_payload);
        second.message_id = Some("message-1".to_string());
        second.chunk_index = Some(1);
        second.chunk_final = Some(true);
        let first_bytes = TunnelCodec::encode(&first).expect("first chunk");
        let second_bytes = TunnelCodec::encode(&second).expect("second chunk");
        let mut decoder = TunnelStreamDecoder::default();
        assert!(decoder.push(&first_bytes).expect("first push").is_empty());
        let frames = decoder.push(&second_bytes).expect("second push");
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].payload.as_deref(), Some(payload.as_str()));
        assert!(frames[0].message_id.is_none());
        assert!(frames[0].chunk_index.is_none());
        assert!(frames[0].chunk_final.is_none());
    }
}
