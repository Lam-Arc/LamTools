//! A scripted model for the CLI demo and for tests.
//!
//! The script is a JSON array of turns. This is not a mock inside the core: the
//! loop, the store, the tools and the approval flow are all the real ones. Only
//! the thing that would cost money to call is replaced.

use std::sync::Mutex;
use sunday_protocol::{CoreError, Model, ModelDelta, ModelRequest, ModelTurn, ToolCall};

pub struct ScriptedModel {
    turns: Mutex<Vec<ModelTurn>>,
}

impl ScriptedModel {
    pub fn from_json(text: &str) -> Result<Self, CoreError> {
        let raw: serde_json::Value = serde_json::from_str(text)
            .map_err(|e| CoreError::invalid(format!("script is not json: {e}")))?;
        let array = raw
            .as_array()
            .ok_or_else(|| CoreError::invalid("script must be a JSON array of turns"))?;
        let mut turns = Vec::new();
        for (index, entry) in array.iter().enumerate() {
            let text = entry
                .get("text")
                .and_then(|v| v.as_str())
                .map(str::to_owned);
            let mut tool_calls = Vec::new();
            if let Some(calls) = entry.get("tool_calls").and_then(|v| v.as_array()) {
                for call in calls {
                    let id = call.get("id").and_then(|v| v.as_str()).ok_or_else(|| {
                        CoreError::invalid(format!("turn {index} call has no id"))
                    })?;
                    let name = call.get("name").and_then(|v| v.as_str()).ok_or_else(|| {
                        CoreError::invalid(format!("turn {index} call has no name"))
                    })?;
                    let args = call.get("args").cloned().unwrap_or(serde_json::json!({}));
                    tool_calls.push(ToolCall {
                        id: id.to_owned(),
                        name: name.to_owned(),
                        args,
                    });
                }
            }
            turns.push(ModelTurn {
                text,
                reasoning: None,
                tool_calls,
                usage: None,
                provider_state: None,
            });
        }
        if turns.is_empty() {
            return Err(CoreError::invalid("script has no turns"));
        }
        Ok(Self {
            turns: Mutex::new(turns),
        })
    }
}

#[async_trait::async_trait]
impl Model for ScriptedModel {
    async fn stream(
        &self,
        _request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError> {
        let mut turns = self.turns.lock().unwrap();
        if turns.is_empty() {
            return Err(CoreError::model(
                "the script ran out of turns, which means the loop asked for more than expected",
            ));
        }
        let turn = turns.remove(0);
        if let Some(text) = &turn.text {
            sink(ModelDelta::Text(text.clone()));
        }
        Ok(turn)
    }
}
