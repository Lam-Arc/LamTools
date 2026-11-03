//! OpenAI Chat Completions wire format: request body, stream assembly, parsing.

use crate::sse::SseEvent;
use serde_json::{json, Map, Value};
use sunday_protocol::{
    CoreError, ImageInput, Message, ModelDelta, ModelRequest, ModelTurn, ToolCall, Usage,
};

pub fn body(request: &ModelRequest) -> Value {
    let mut messages = Vec::new();
    for message in &request.messages {
        messages.push(message_json(message));
    }
    let mut body = Map::new();
    body.insert("model".into(), json!(request.model_id));
    body.insert("messages".into(), Value::Array(messages));
    body.insert("stream".into(), json!(true));
    body.insert("stream_options".into(), json!({"include_usage": true}));
    if let Some(temperature) = request.temperature {
        body.insert("temperature".into(), json!(temperature));
    }
    if let Some(max) = request.max_output_tokens {
        body.insert("max_tokens".into(), json!(max));
    }
    if !request.tools.is_empty() {
        let tools: Vec<Value> = request
            .tools
            .iter()
            .map(|t| {
                json!({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    }
                })
            })
            .collect();
        body.insert("tools".into(), Value::Array(tools));
    }
    Value::Object(body)
}

fn message_json(message: &Message) -> Value {
    match message {
        Message::System { content } => json!({"role": "system", "content": content}),
        Message::User { content } => json!({"role": "user", "content": content}),
        Message::UserMultimodal { content, images } => json!({
            "role": "user",
            "content": content_parts(content, images),
        }),
        Message::Assistant { content } => json!({"role": "assistant", "content": content}),
        Message::AssistantToolCalls { calls, content } => json!({
            "role": "assistant",
            "content": content,
            "tool_calls": calls.iter().map(|c| json!({
                "id": c.id,
                "type": "function",
                "function": {"name": c.name, "arguments": c.args.to_string()},
            })).collect::<Vec<_>>(),
        }),
        Message::ToolResult {
            call_id, content, ..
        } => {
            json!({"role": "tool", "tool_call_id": call_id, "content": content})
        }
    }
}

fn content_parts(text: &str, images: &[ImageInput]) -> Value {
    let mut parts = vec![json!({"type": "text", "text": text})];
    for image in images {
        parts.push(json!({
            "type": "image_url",
            "image_url": {"url": format!("data:{};base64,{}", image.mime, image.data_b64)},
        }));
    }
    Value::Array(parts)
}

#[derive(Default)]
struct PartialCall {
    id: String,
    name: String,
    args: String,
}

#[derive(Default)]
pub struct Assembler {
    text: String,
    reasoning: String,
    calls: Vec<PartialCall>,
    usage: Option<Usage>,
}

impl Assembler {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&mut self, event: &SseEvent) -> Result<Vec<ModelDelta>, CoreError> {
        if event.data.trim().is_empty() || event.data.trim() == "[DONE]" {
            return Ok(Vec::new());
        }
        let value: Value = serde_json::from_str(&event.data)
            .map_err(|e| CoreError::model(format!("openai frame is not json: {e}")))?;

        let mut out = Vec::new();

        if let Some(usage) = value.get("usage").filter(|u| !u.is_null()) {
            let parsed = Usage {
                input_tokens: usage
                    .get("prompt_tokens")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as u32,
                output_tokens: usage
                    .get("completion_tokens")
                    .and_then(|v| v.as_u64())
                    .unwrap_or(0) as u32,
            };
            self.usage = Some(parsed);
            out.push(ModelDelta::Usage(parsed));
        }

        let Some(choices) = value.get("choices").and_then(|c| c.as_array()) else {
            return Ok(out);
        };
        for choice in choices {
            let Some(delta) = choice.get("delta") else {
                continue;
            };

            if let Some(reasoning) = delta.get("reasoning_content").and_then(|v| v.as_str()) {
                if !reasoning.is_empty() {
                    self.reasoning.push_str(reasoning);
                    out.push(ModelDelta::Reasoning(reasoning.to_owned()));
                }
            }
            if let Some(text) = delta.get("content").and_then(|v| v.as_str()) {
                if !text.is_empty() {
                    self.text.push_str(text);
                    out.push(ModelDelta::Text(text.to_owned()));
                }
            }
            if let Some(calls) = delta.get("tool_calls").and_then(|v| v.as_array()) {
                for call in calls {
                    let index = call.get("index").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                    while self.calls.len() <= index {
                        self.calls.push(PartialCall::default());
                    }
                    let slot = &mut self.calls[index];
                    let id = call.get("id").and_then(|v| v.as_str()).map(str::to_owned);
                    let name = call
                        .get("function")
                        .and_then(|f| f.get("name"))
                        .and_then(|v| v.as_str())
                        .map(str::to_owned);
                    let fragment = call
                        .get("function")
                        .and_then(|f| f.get("arguments"))
                        .and_then(|v| v.as_str())
                        .unwrap_or_default()
                        .to_owned();
                    if let Some(id) = &id {
                        slot.id = id.clone();
                    }
                    if let Some(name) = &name {
                        slot.name = name.clone();
                    }
                    slot.args.push_str(&fragment);
                    out.push(ModelDelta::ToolCallDelta {
                        index,
                        id,
                        name,
                        args_fragment: fragment,
                    });
                }
            }
        }
        Ok(out)
    }

    pub fn finish(self) -> Result<ModelTurn, CoreError> {
        let mut calls = Vec::new();
        for (index, partial) in self.calls.into_iter().enumerate() {
            if partial.name.is_empty() {
                return Err(CoreError::model(format!(
                    "tool call {index} finished without a name"
                )));
            }
            let args = if partial.args.trim().is_empty() {
                Value::Object(Map::new())
            } else {
                serde_json::from_str(&partial.args).map_err(|e| {
                    CoreError::model(format!("tool call {index} arguments are not json: {e}"))
                })?
            };
            let id = if partial.id.is_empty() {
                format!("call_{index}")
            } else {
                partial.id
            };
            calls.push(ToolCall {
                id,
                name: partial.name,
                args,
            });
        }
        Ok(ModelTurn {
            text: if self.text.is_empty() {
                None
            } else {
                Some(self.text)
            },
            reasoning: if self.reasoning.is_empty() {
                None
            } else {
                Some(self.reasoning)
            },
            tool_calls: calls,
            usage: self.usage,
            provider_state: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sunday_protocol::ToolDefinition;

    fn event(data: Value) -> SseEvent {
        SseEvent {
            event: String::new(),
            data: data.to_string(),
        }
    }

    fn request() -> ModelRequest {
        ModelRequest {
            model_id: "test-model".into(),
            messages: vec![
                Message::System {
                    content: "be careful".into(),
                },
                Message::User {
                    content: "写一个文件".into(),
                },
            ],
            tools: vec![ToolDefinition {
                name: "write_file".into(),
                description: "write".into(),
                input_schema: json!({"type": "object"}),
            }],
            temperature: Some(0.2),
            max_output_tokens: Some(512),
        }
    }

    #[test]
    fn body_carries_model_messages_tools_and_stream_flag() {
        let body = body(&request());
        assert_eq!(body["model"], "test-model");
        assert_eq!(body["stream"], true);
        assert_eq!(body["messages"][0]["role"], "system");
        assert_eq!(body["messages"][1]["role"], "user");
        assert_eq!(body["tools"][0]["function"]["name"], "write_file");
        assert_eq!(body["temperature"], 0.2);
        assert_eq!(body["max_tokens"], 512);
    }

    #[test]
    fn multimodal_user_message_becomes_content_parts() {
        let mut req = request();
        req.messages = vec![Message::UserMultimodal {
            content: "看图".into(),
            images: vec![ImageInput {
                mime: "image/png".into(),
                data_b64: "AAA".into(),
            }],
        }];
        let body = body(&req);
        let parts = body["messages"][0]["content"].as_array().unwrap();
        assert_eq!(parts[0]["type"], "text");
        assert_eq!(parts[1]["type"], "image_url");
        assert!(parts[1]["image_url"]["url"]
            .as_str()
            .unwrap()
            .starts_with("data:image/png;base64,"));
    }

    #[test]
    fn text_deltas_accumulate_into_one_turn() {
        let mut a = Assembler::new();
        let mut deltas = Vec::new();
        deltas.extend(
            a.push(&event(json!({"choices":[{"delta":{"content":"你"}}]})))
                .unwrap(),
        );
        deltas.extend(
            a.push(&event(json!({"choices":[{"delta":{"content":"好"}}]})))
                .unwrap(),
        );
        let turn = a.finish().unwrap();
        assert_eq!(turn.text.unwrap(), "你好");
        assert_eq!(
            deltas,
            vec![ModelDelta::Text("你".into()), ModelDelta::Text("好".into())]
        );
    }

    #[test]
    fn tool_call_fragments_are_joined_by_index() {
        let mut a = Assembler::new();
        a.push(&event(json!({"choices":[{"delta":{"tool_calls":[
            {"index":0,"id":"call_a","function":{"name":"write_file","arguments":"{\"path\":"}}
        ]}}]})))
        .unwrap();
        a.push(&event(json!({"choices":[{"delta":{"tool_calls":[
            {"index":0,"function":{"arguments":"\"a.txt\"}"}}
        ]}}]})))
        .unwrap();
        let turn = a.finish().unwrap();
        assert_eq!(turn.tool_calls.len(), 1);
        assert_eq!(turn.tool_calls[0].id, "call_a");
        assert_eq!(turn.tool_calls[0].name, "write_file");
        assert_eq!(turn.tool_calls[0].args["path"], "a.txt");
    }

    #[test]
    fn two_tool_calls_stay_separate() {
        let mut a = Assembler::new();
        a.push(&event(json!({"choices":[{"delta":{"tool_calls":[
            {"index":0,"id":"c0","function":{"name":"a","arguments":"{}"}},
            {"index":1,"id":"c1","function":{"name":"b","arguments":"{}"}}
        ]}}]})))
        .unwrap();
        let turn = a.finish().unwrap();
        assert_eq!(turn.tool_calls.len(), 2);
        assert_eq!(turn.tool_calls[1].name, "b");
    }

    #[test]
    fn usage_is_reported_and_kept() {
        let mut a = Assembler::new();
        let deltas = a
            .push(&event(
                json!({"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7}}),
            ))
            .unwrap();
        assert_eq!(
            deltas,
            vec![ModelDelta::Usage(Usage {
                input_tokens: 11,
                output_tokens: 7
            })]
        );
        assert_eq!(a.finish().unwrap().usage.unwrap().output_tokens, 7);
    }

    #[test]
    fn a_tool_call_without_a_name_is_a_defect_not_a_silent_empty_call() {
        let mut a = Assembler::new();
        a.push(&event(json!({"choices":[{"delta":{"tool_calls":[
            {"index":0,"id":"x","function":{"arguments":"{}"}}
        ]}}]})))
        .unwrap();
        let err = a.finish().unwrap_err();
        assert!(matches!(err, CoreError::Model { .. }));
    }

    #[test]
    fn malformed_frame_is_reported_not_swallowed() {
        let mut a = Assembler::new();
        let err = a
            .push(&SseEvent {
                event: String::new(),
                data: "{not json".into(),
            })
            .unwrap_err();
        assert!(matches!(err, CoreError::Model { .. }));
    }

    #[test]
    fn empty_arguments_become_an_empty_object_not_a_failure() {
        let mut a = Assembler::new();
        a.push(&event(json!({"choices":[{"delta":{"tool_calls":[
            {"index":0,"id":"x","function":{"name":"ping","arguments":""}}
        ]}}]})))
        .unwrap();
        let turn = a.finish().unwrap();
        assert_eq!(turn.tool_calls[0].args, json!({}));
    }
}
