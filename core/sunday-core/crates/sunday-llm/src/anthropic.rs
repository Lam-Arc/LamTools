//! Anthropic Messages wire format: request body, stream assembly, parsing.
//!
//! Differences from OpenAI that the trial had to handle explicitly:
//! the system prompt is a top-level field, `max_tokens` is mandatory,
//! tool arguments arrive as `partial_json` fragments, and block indexes are
//! reused between text and tool blocks.

use crate::sse::SseEvent;
use serde_json::{json, Map, Value};
use sunday_protocol::{
    CoreError, ImageInput, Message, ModelDelta, ModelRequest, ModelTurn, ToolCall, Usage,
};

const DEFAULT_MAX_TOKENS: u32 = 1024;

pub fn body(request: &ModelRequest) -> Value {
    let mut system_parts: Vec<String> = Vec::new();
    let mut messages = Vec::new();
    for message in &request.messages {
        match message {
            Message::System { content } => system_parts.push(content.clone()),
            Message::User { content } => messages.push(json!({"role": "user", "content": content})),
            Message::UserMultimodal { content, images } => messages.push(json!({
                "role": "user",
                "content": parts(content, images),
            })),
            Message::Assistant { content } => {
                messages.push(json!({"role": "assistant", "content": content}))
            }
            Message::AssistantToolCalls { calls, content } => {
                let mut blocks = Vec::new();
                if let Some(text) = content {
                    if !text.is_empty() {
                        blocks.push(json!({"type": "text", "text": text}));
                    }
                }
                for call in calls {
                    blocks.push(json!({
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.args,
                    }));
                }
                messages.push(json!({"role": "assistant", "content": blocks}));
            }
            Message::ToolResult {
                call_id, content, ..
            } => messages.push(json!({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": content,
                }],
            })),
        }
    }

    let mut body = Map::new();
    body.insert("model".into(), json!(request.model_id));
    body.insert(
        "max_tokens".into(),
        json!(request.max_output_tokens.unwrap_or(DEFAULT_MAX_TOKENS)),
    );
    body.insert("stream".into(), json!(true));
    body.insert("messages".into(), Value::Array(messages));
    if !system_parts.is_empty() {
        body.insert("system".into(), json!(system_parts.join("\n\n")));
    }
    if let Some(temperature) = request.temperature {
        body.insert("temperature".into(), json!(temperature));
    }
    if !request.tools.is_empty() {
        let tools: Vec<Value> = request
            .tools
            .iter()
            .map(|t| {
                json!({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                })
            })
            .collect();
        body.insert("tools".into(), Value::Array(tools));
    }
    Value::Object(body)
}

fn parts(text: &str, images: &[ImageInput]) -> Value {
    let mut blocks = vec![json!({"type": "text", "text": text})];
    for image in images {
        blocks.push(json!({
            "type": "image",
            "source": {"type": "base64", "media_type": image.mime, "data": image.data_b64},
        }));
    }
    Value::Array(blocks)
}

#[derive(Default)]
struct Block {
    kind: String,
    id: String,
    name: String,
    args: String,
}

#[derive(Default)]
pub struct Assembler {
    text: String,
    blocks: Vec<Block>,
    input_tokens: u32,
    output_tokens: u32,
}

impl Assembler {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&mut self, event: &SseEvent) -> Result<Vec<ModelDelta>, CoreError> {
        if event.data.trim().is_empty() {
            return Ok(Vec::new());
        }
        let value: Value = serde_json::from_str(&event.data)
            .map_err(|e| CoreError::model(format!("anthropic frame is not json: {e}")))?;
        let kind = value
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or(event.event.as_str())
            .to_owned();

        let mut out = Vec::new();
        match kind.as_str() {
            "message_start" => {
                if let Some(tokens) = value
                    .get("message")
                    .and_then(|m| m.get("usage"))
                    .and_then(|u| u.get("input_tokens"))
                    .and_then(|v| v.as_u64())
                {
                    self.input_tokens = tokens as u32;
                }
            }
            "content_block_start" => {
                let index = value.get("index").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                let block = value.get("content_block").cloned().unwrap_or(Value::Null);
                while self.blocks.len() <= index {
                    self.blocks.push(Block::default());
                }
                let slot = &mut self.blocks[index];
                slot.kind = block
                    .get("type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_owned();
                if let Some(id) = block.get("id").and_then(|v| v.as_str()) {
                    slot.id = id.to_owned();
                }
                if let Some(name) = block.get("name").and_then(|v| v.as_str()) {
                    slot.name = name.to_owned();
                }
            }
            "content_block_delta" => {
                let index = value.get("index").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                while self.blocks.len() <= index {
                    self.blocks.push(Block::default());
                }
                let delta = value.get("delta").cloned().unwrap_or(Value::Null);
                match delta.get("type").and_then(|v| v.as_str()).unwrap_or("") {
                    "text_delta" => {
                        let text = delta.get("text").and_then(|v| v.as_str()).unwrap_or("");
                        if !text.is_empty() {
                            self.text.push_str(text);
                            out.push(ModelDelta::Text(text.to_owned()));
                        }
                    }
                    "thinking_delta" => {
                        let text = delta.get("thinking").and_then(|v| v.as_str()).unwrap_or("");
                        if !text.is_empty() {
                            out.push(ModelDelta::Reasoning(text.to_owned()));
                        }
                    }
                    "input_json_delta" => {
                        let fragment = delta
                            .get("partial_json")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_owned();
                        let slot = &mut self.blocks[index];
                        slot.args.push_str(&fragment);
                        out.push(ModelDelta::ToolCallDelta {
                            index,
                            id: if slot.id.is_empty() {
                                None
                            } else {
                                Some(slot.id.clone())
                            },
                            name: if slot.name.is_empty() {
                                None
                            } else {
                                Some(slot.name.clone())
                            },
                            args_fragment: fragment,
                        });
                    }
                    _ => {}
                }
            }
            "message_delta" => {
                if let Some(tokens) = value
                    .get("usage")
                    .and_then(|u| u.get("output_tokens"))
                    .and_then(|v| v.as_u64())
                {
                    self.output_tokens = tokens as u32;
                }
            }
            "error" => {
                let message = value
                    .get("error")
                    .and_then(|e| e.get("message"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("anthropic stream error");
                return Err(CoreError::model(message.to_owned()));
            }
            _ => {}
        }
        if (self.input_tokens > 0 || self.output_tokens > 0)
            && matches!(kind.as_str(), "message_delta" | "message_stop")
        {
            out.push(ModelDelta::Usage(Usage {
                input_tokens: self.input_tokens,
                output_tokens: self.output_tokens,
            }));
        }
        Ok(out)
    }

    pub fn finish(self) -> Result<ModelTurn, CoreError> {
        let mut calls = Vec::new();
        for (index, block) in self.blocks.into_iter().enumerate() {
            if block.kind != "tool_use" {
                continue;
            }
            if block.name.is_empty() {
                return Err(CoreError::model(format!("tool block {index} has no name")));
            }
            let args = if block.args.trim().is_empty() {
                Value::Object(Map::new())
            } else {
                serde_json::from_str(&block.args).map_err(|e| {
                    CoreError::model(format!("tool block {index} arguments are not json: {e}"))
                })?
            };
            calls.push(ToolCall {
                id: if block.id.is_empty() {
                    format!("toolu_{index}")
                } else {
                    block.id
                },
                name: block.name,
                args,
            });
        }
        let usage = if self.input_tokens == 0 && self.output_tokens == 0 {
            None
        } else {
            Some(Usage {
                input_tokens: self.input_tokens,
                output_tokens: self.output_tokens,
            })
        };
        Ok(ModelTurn {
            text: if self.text.is_empty() {
                None
            } else {
                Some(self.text)
            },
            reasoning: None,
            tool_calls: calls,
            usage,
            provider_state: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sunday_protocol::ToolDefinition;

    fn ev(value: Value) -> SseEvent {
        let event = value
            .get("type")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_owned();
        SseEvent {
            event,
            data: value.to_string(),
        }
    }

    fn request() -> ModelRequest {
        ModelRequest {
            model_id: "claude-test".into(),
            messages: vec![
                Message::System {
                    content: "be careful".into(),
                },
                Message::User {
                    content: "hi".into(),
                },
            ],
            tools: vec![ToolDefinition {
                name: "read_file".into(),
                description: "read".into(),
                input_schema: json!({"type": "object"}),
            }],
            temperature: None,
            max_output_tokens: None,
        }
    }

    #[test]
    fn system_prompt_is_lifted_out_of_messages() {
        let body = body(&request());
        assert_eq!(body["system"], "be careful");
        assert_eq!(body["messages"].as_array().unwrap().len(), 1);
        assert_eq!(body["messages"][0]["role"], "user");
    }

    #[test]
    fn max_tokens_is_mandatory_and_defaulted() {
        let body = body(&request());
        assert_eq!(body["max_tokens"], DEFAULT_MAX_TOKENS);
    }

    #[test]
    fn tools_use_input_schema_not_parameters() {
        let body = body(&request());
        assert_eq!(body["tools"][0]["input_schema"]["type"], "object");
        assert!(body["tools"][0].get("parameters").is_none());
    }

    #[test]
    fn text_delta_accumulates() {
        let mut a = Assembler::new();
        a.push(&ev(
            json!({"type":"message_start","message":{"usage":{"input_tokens":9}}}),
        ))
        .unwrap();
        a.push(&ev(
            json!({"type":"content_block_start","index":0,"content_block":{"type":"text"}}),
        ))
        .unwrap();
        a.push(&ev(json!({"type":"content_block_delta","index":0,
            "delta":{"type":"text_delta","text":"你"}})))
            .unwrap();
        a.push(&ev(json!({"type":"content_block_delta","index":0,
            "delta":{"type":"text_delta","text":"好"}})))
            .unwrap();
        a.push(&ev(
            json!({"type":"message_delta","delta":{},"usage":{"output_tokens":2}}),
        ))
        .unwrap();
        let turn = a.finish().unwrap();
        assert_eq!(turn.text.unwrap(), "你好");
        assert_eq!(
            turn.usage.unwrap(),
            Usage {
                input_tokens: 9,
                output_tokens: 2
            }
        );
    }

    #[test]
    fn tool_use_fragments_are_joined() {
        let mut a = Assembler::new();
        a.push(&ev(json!({"type":"content_block_start","index":0,
            "content_block":{"type":"tool_use","id":"toolu_1","name":"read_file"}})))
            .unwrap();
        a.push(&ev(json!({"type":"content_block_delta","index":0,
            "delta":{"type":"input_json_delta","partial_json":"{\"path\":"}})))
            .unwrap();
        a.push(&ev(json!({"type":"content_block_delta","index":0,
            "delta":{"type":"input_json_delta","partial_json":"\"a.txt\"}"}})))
            .unwrap();
        let turn = a.finish().unwrap();
        assert_eq!(turn.tool_calls[0].name, "read_file");
        assert_eq!(turn.tool_calls[0].id, "toolu_1");
        assert_eq!(turn.tool_calls[0].args["path"], "a.txt");
    }

    #[test]
    fn text_and_tool_blocks_coexist() {
        let mut a = Assembler::new();
        a.push(&ev(
            json!({"type":"content_block_start","index":0,"content_block":{"type":"text"}}),
        ))
        .unwrap();
        a.push(&ev(json!({"type":"content_block_delta","index":0,
            "delta":{"type":"text_delta","text":"先读一下"}})))
            .unwrap();
        a.push(&ev(json!({"type":"content_block_start","index":1,
            "content_block":{"type":"tool_use","id":"t1","name":"read_file"}})))
            .unwrap();
        let turn = a.finish().unwrap();
        assert_eq!(turn.text.unwrap(), "先读一下");
        assert_eq!(turn.tool_calls.len(), 1);
    }

    #[test]
    fn stream_error_event_becomes_a_model_error() {
        let mut a = Assembler::new();
        let err = a
            .push(&ev(
                json!({"type":"error","error":{"type":"overloaded_error","message":"overloaded"}}),
            ))
            .unwrap_err();
        assert!(matches!(err, CoreError::Model { .. }));
    }
}
