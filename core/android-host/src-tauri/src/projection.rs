//! The `core/runItem` projection the shared UI actually renders.
//!
//! The core's own event language (`turn/accepted`, `item/tool_prepared`, …) describes
//! what the runner did. The screen does not read it: `core/ui/src/appServer/store.ts`
//! consumes `core/runItem` notifications and dispatches on `payload.kind`. Shipping the
//! runner's language straight to the webview meant the events arrived, were parsed, and
//! then matched nothing — the transcript stayed empty while the model answered.
//!
//! This is the boundary where one becomes the other. The rules it follows are taken
//! from the desktop core's projection (`event/runtime_projection.py`) so both cores
//! describe the same fact the same way, and so the UI needs no second code path:
//!
//! * `item_id` is stable and derived, never random: a tool call keeps one id from
//!   approval through execution, so an approval card updates its own row instead of
//!   spawning a duplicate.
//! * `event_id` comes from the journal seq, so the same fact replayed after a resume
//!   is the same id and the client's seen-set drops the copy.
//! * A turn's identity is carried forward: `run_started` names it, and every later
//!   item in that thread belongs to it until the next one starts.
//!
//! Anything without a rendered meaning (model started, internal bookkeeping) projects
//! to `None` and never reaches the webview.

use std::collections::{HashMap, HashSet};

use serde_json::{json, Value};

/// What the desktop core offers on an approval card. Copied rather than invented so a
/// phone and a desktop show the same two buttons with the same wire responses.
fn approval_options() -> Value {
    json!([
        {
            "id": "approve",
            "label": "批准执行",
            "description": "允许后端继续执行这个工具调用。",
            "response": "approve",
        },
        {
            "id": "deny",
            "label": "拒绝执行",
            "description": "不执行这个工具调用，本轮停在等待点。",
            "response": "deny",
        },
    ])
}

/// Per-conversation state the projection needs across events.
///
/// One instance per host process, shared by the live sink and the resume path, so
/// history and realtime cannot disagree about which turn an item belongs to.
#[derive(Default)]
pub struct Projector {
    turn_of: HashMap<String, String>,
    /// Tool calls seen, so an approval card can name the tool it is asking about.
    calls: HashMap<String, Value>,
    /// Threads whose assistant text already went out through `model_completed`.
    spoke: HashSet<String>,
}

impl Projector {
    pub fn new() -> Self {
        Self::default()
    }

    /// Projects one journal envelope, or `None` when it has no rendered meaning.
    pub fn project(&mut self, envelope: &Value) -> Option<Value> {
        let thread = envelope.get("thread_id").and_then(Value::as_str)?.to_owned();
        let method = envelope.get("method").and_then(Value::as_str)?.to_owned();
        let seq = envelope.get("seq").and_then(Value::as_u64).unwrap_or(0);
        let mut event_id = envelope
            .get("event_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        // A closure reported outside the journal (an expiry sweep) has no seq, so its
        // envelope id carries no anchor of its own. Several closures in one reply
        // would then share one identity and the client, which dedupes on it, would
        // keep only the first — leaving every other card looking answerable.
        if seq == 0 {
            let discriminant = envelope
                .get("payload")
                .and_then(|value| value.get("request_id").or_else(|| value.get("approval_id")))
                .and_then(Value::as_str)
                .unwrap_or_default();
            if !discriminant.is_empty() {
                event_id = format!("{}:{}", event_id, discriminant);
            }
        }
        let payload = envelope
            .get("payload")
            .cloned()
            .unwrap_or_else(|| json!({}));
        let text = |key: &str| {
            payload
                .get(key)
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned()
        };
        let call_id = |payload: &Value| {
            payload
                .get("tool_call_id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned()
        };

        // A turn is named once, by the event that starts it.
        if method == "turn/started" {
            if let Some(turn) = payload.get("turn_id").and_then(Value::as_str) {
                if !turn.is_empty() {
                    self.turn_of.insert(thread.clone(), turn.to_owned());
                }
            }
        }
        // An explicit `turn_id` wins, including an empty one. A closure reported long
        // after its turn ended must not be attributed to it: the client treats an
        // `approval_response` as resuming the turn it names, so pointing one at a
        // finished turn revived it and the composer went back to offering Stop.
        let turn = match payload.get("turn_id").and_then(Value::as_str) {
            Some(explicit) => explicit.to_owned(),
            None => self.turn_of.get(&thread).cloned().unwrap_or_default(),
        };
        let tool_item = |call: &str| format!("{thread}:{turn}:{call}:tool");

        let (kind, item_id, status, body): (&str, String, &str, Value) = match method.as_str() {
            // The user's own instruction. `command_accepted` carries its text because
            // a resumed screen must be able to show what was asked without a second
            // lookup that does not survive a restart.
            "turn/accepted" => {
                let content = text("text");
                if content.trim().is_empty() {
                    return None;
                }
                let client = envelope
                    .get("client_message_id")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let id = if client.is_empty() {
                    format!("{thread}:user:{seq}")
                } else {
                    format!("{thread}:user:{client}")
                };
                (
                    "message",
                    id,
                    "completed",
                    json!({ "type": "userMessage", "role": "user", "content": content }),
                )
            }
            "turn/started" => (
                "status",
                format!("{thread}:{turn}:status"),
                "running",
                json!({ "type": "status", "status": "running" }),
            ),
            "turn/model_completed" => {
                let content = text("text");
                if content.trim().is_empty() {
                    return None;
                }
                self.spoke.insert(thread.clone());
                let round = payload.get("round").and_then(Value::as_u64).unwrap_or(0);
                (
                    "message",
                    format!("{thread}:{turn}:assistant:{round}"),
                    "completed",
                    json!({ "type": "agentMessage", "role": "assistant", "content": content }),
                )
            }
            "item/tool_prepared" => {
                let call = call_id(&payload);
                if call.is_empty() {
                    return None;
                }
                let name = text("name");
                let args = payload.get("arguments").cloned().unwrap_or(Value::Null);
                self.calls.insert(
                    call.clone(),
                    json!({ "name": name, "arguments": args }),
                );
                (
                    "tool_call",
                    tool_item(&call),
                    "waiting",
                    json!({
                        "type": "dynamicToolCall",
                        "tool_call_id": call,
                        "tool_name": name,
                        "tool_args": args,
                    }),
                )
            }
            // The card and the call share one item id, so approving updates the row
            // the user is looking at instead of adding a second one.
            "item/approval_request" => {
                let call = call_id(&payload);
                let request = payload
                    .get("request_id")
                    .or_else(|| payload.get("approval_id"))
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned();
                if request.is_empty() {
                    return None;
                }
                let known = self.calls.get(&call).cloned().unwrap_or(Value::Null);
                let tool_name = known
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned();
                let tool_args = known.get("arguments").cloned().unwrap_or(Value::Null);
                let message = if tool_name.is_empty() {
                    "等待确认后执行工具调用".to_owned()
                } else {
                    format!("等待确认：{tool_name}")
                };
                (
                    "approval_request",
                    tool_item(&call),
                    "waiting",
                    json!({
                        "type": "serverRequest",
                        "request_id": request,
                        "tool_call_id": call,
                        "kind": "approval",
                        "message": message,
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                        "options": approval_options(),
                        // `coreDecisionRequestId` reads `metadata.request_id`, not the
                        // top-level field: a card that carried the id only at the top
                        // rendered its buttons and then sent an empty request id, so
                        // approving did nothing at all.
                        // `coreDecisionSelectionPlan` reads `metadata.waitingRequest.request_id`
                        // and nothing else; when that misses it degrades to "send this as a
                        // normal message", so the click looks answered and the approval is
                        // never sent. Both shapes are provided so neither reader can miss it.
                        "metadata": {
                            "request_id": request,
                            "tool_call_id": call,
                            "waitingRequest": { "request_id": request, "kind": "approval" },
                        },
                    }),
                )
            }
            "item/approval_resolved" => {
                let call = call_id(&payload);
                let request = payload
                    .get("request_id")
                    .or_else(|| payload.get("approval_id"))
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned();
                if request.is_empty() {
                    return None;
                }
                let decision = text("decision");
                let state = text("state");
                (
                    "approval_response",
                    tool_item(&call),
                    "completed",
                    json!({
                        "type": "serverRequest",
                        "request_id": request,
                        "tool_call_id": call,
                        "decision": decision,
                        // The client closes the card on `state: "ending"`; dropping
                        // it here left an expired card looking answerable forever.
                        "state": state,
                        "metadata": { "request_id": request },
                    }),
                )
            }
            "item/tool_dispatched" => {
                let call = call_id(&payload);
                if call.is_empty() {
                    return None;
                }
                let known = self.calls.get(&call).cloned().unwrap_or(Value::Null);
                (
                    "tool_call",
                    tool_item(&call),
                    "running",
                    json!({
                        "type": "dynamicToolCall",
                        "tool_call_id": call,
                        "tool_name": known.get("name").cloned().unwrap_or(Value::Null),
                        "tool_args": known.get("arguments").cloned().unwrap_or(Value::Null),
                    }),
                )
            }
            "item/completed" | "item/failed" => {
                let call = call_id(&payload);
                if call.is_empty() {
                    return None;
                }
                let known = self.calls.get(&call).cloned().unwrap_or(Value::Null);
                let content = payload
                    .get("content")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
                    .or_else(|| payload.get("error").and_then(Value::as_str).map(str::to_owned))
                    .unwrap_or_default();
                let failed = method == "item/failed"
                    || payload
                        .get("is_error")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                (
                    "tool_result",
                    tool_item(&call),
                    if failed { "failed" } else { "completed" },
                    json!({
                        "type": "dynamicToolCall",
                        "tool_call_id": call,
                        "tool_name": known.get("name").cloned().unwrap_or(Value::Null),
                        "content": content,
                        "is_error": failed,
                    }),
                )
            }
            "item/guidance" => {
                let content = text("text");
                if content.trim().is_empty() {
                    return None;
                }
                (
                    "message",
                    format!("{thread}:guidance:{seq}"),
                    "completed",
                    json!({ "type": "userMessage", "role": "user", "content": content }),
                )
            }
            // A turn closing is a status change, not a message — unless the run
            // produced text that never went out through `model_completed`, which is
            // the case for a run with no tool calls on some providers.
            // A turn that closes is first of all a status change. Emitting the reply
            // instead — which is what an either/or did — left the thread reading
            // "running" forever, so the composer showed Stop and the next send was
            // refused. The reply itself arrives on `model_completed`.
            "turn/completed" => (
                "status",
                format!("{thread}:{turn}:status"),
                "completed",
                json!({ "type": "status", "status": "completed" }),
            ),
            "turn/cancelled" => (
                "status",
                format!("{thread}:{turn}:status"),
                "cancelled",
                json!({ "type": "status", "status": "cancelled" }),
            ),
            // The run stopped without knowing whether a side effect landed. The turn
            // is *not* complete: it waits for a human decision, and saying "completed"
            // here would tell the user the task finished.
            "turn/waiting_for_reconciliation" => (
                "status",
                format!("{thread}:{turn}:status"),
                "waiting",
                json!({ "type": "status", "status": "waiting" }),
            ),
            _ => return None,
        };

        // `turn/completed` ends the turn's speaking window.
        if matches!(method.as_str(), "turn/completed" | "turn/cancelled") {
            self.spoke.remove(&thread);
        }

        #[cfg(debug_assertions)]
        if kind == "approval_request" {
            println!(
                "projection approval_request request_id={} tool_call_id={}",
                body.get("request_id").and_then(Value::as_str).unwrap_or("?"),
                body.get("tool_call_id").and_then(Value::as_str).unwrap_or("?"),
            );
        }

        Some(json!({
            "thread_id": thread,
            "seq": seq,
            "method": "core/runItem",
            "event_id": event_id,
            "created_at": "",
            "payload": {
                "kind": kind,
                "thread_id": thread,
                "event_id": event_id,
                "seq": seq,
                "turn_id": turn,
                "item_id": item_id,
                "status": status,
                "payload": body,
                "created_at_ms": 0,
            },
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn envelope(method: &str, seq: u64, payload: Value) -> Value {
        json!({
            "thread_id": "th",
            "seq": seq,
            "method": method,
            "event_id": format!("th:{seq}"),
            "created_at": "",
            "payload": payload,
        })
    }

    fn run_item(projector: &mut Projector, method: &str, seq: u64, payload: Value) -> Value {
        projector
            .project(&envelope(method, seq, payload))
            .unwrap_or_else(|| panic!("{method} projected to nothing"))
    }

    /// The user's instruction must reach the transcript, with its own text.
    #[test]
    fn an_accepted_command_becomes_a_user_message() {
        let mut projector = Projector::new();
        let item = run_item(&mut projector, "turn/accepted", 1, json!({"kind": "turn_start", "text": "make notes.md"}));
        assert_eq!(item["method"], "core/runItem");
        assert_eq!(item["payload"]["kind"], "message");
        assert_eq!(item["payload"]["payload"]["role"], "user");
        assert_eq!(item["payload"]["payload"]["content"], "make notes.md");
        assert_eq!(item["payload"]["event_id"], "th:1");
    }

    /// A command with no text is bookkeeping, not a message: projecting it would
    /// render an empty bubble.
    #[test]
    fn an_accepted_command_without_text_projects_to_nothing() {
        let mut projector = Projector::new();
        assert!(projector
            .project(&envelope("turn/accepted", 1, json!({"kind": "turn_start"})))
            .is_none());
    }

    /// The approval card has to name the tool it is asking about, and must reuse the
    /// tool call's own item id so approving updates that row instead of adding one.
    #[test]
    fn an_approval_names_the_tool_and_reuses_the_call_row() {
        let mut projector = Projector::new();
        run_item(&mut projector, "turn/started", 2, json!({"turn_id": "turn-1"}));
        let prepared = run_item(
            &mut projector,
            "item/tool_prepared",
            3,
            json!({"tool_call_id": "c1", "name": "write_file", "arguments": {"path": "notes.md"}}),
        );
        let approval = run_item(
            &mut projector,
            "item/approval_request",
            4,
            json!({"tool_call_id": "c1", "request_id": "r1", "approval_id": "r1"}),
        );
        assert_eq!(approval["payload"]["kind"], "approval_request");
        assert_eq!(approval["payload"]["status"], "waiting");
        assert_eq!(
            approval["payload"]["item_id"], prepared["payload"]["item_id"],
            "the card is not attached to the tool row it is asking about"
        );
        assert_eq!(approval["payload"]["payload"]["tool_name"], "write_file");
        assert_eq!(approval["payload"]["payload"]["request_id"], "r1");
        assert_eq!(approval["payload"]["turn_id"], "turn-1");
        assert!(approval["payload"]["payload"]["options"].is_array());
    }

    /// A tool's result replaces the same row, and a failure is not a success.
    #[test]
    fn a_tool_result_closes_its_own_row() {
        let mut projector = Projector::new();
        run_item(&mut projector, "turn/started", 1, json!({"turn_id": "t"}));
        let call = run_item(&mut projector, "item/tool_prepared", 2, json!({"tool_call_id": "c1", "name": "write_file", "arguments": {}}));
        let done = run_item(&mut projector, "item/completed", 3, json!({"tool_call_id": "c1", "content": "wrote 3 lines"}));
        assert_eq!(done["payload"]["item_id"], call["payload"]["item_id"]);
        assert_eq!(done["payload"]["kind"], "tool_result");
        assert_eq!(done["payload"]["status"], "completed");
        assert_eq!(done["payload"]["payload"]["content"], "wrote 3 lines");

        let failed = run_item(&mut projector, "item/failed", 4, json!({"tool_call_id": "c1", "error": "permission denied"}));
        assert_eq!(failed["payload"]["status"], "failed");
    }

    /// Waiting for a human is not completion. Marking the turn done here would tell
    /// the user the task finished while a side effect is still unknown.
    #[test]
    fn waiting_for_reconciliation_is_not_a_completion() {
        let mut projector = Projector::new();
        run_item(&mut projector, "turn/started", 1, json!({"turn_id": "t"}));
        let item = run_item(&mut projector, "turn/waiting_for_reconciliation", 2, json!({}));
        assert_eq!(item["payload"]["kind"], "status");
        assert_eq!(item["payload"]["payload"]["status"], "waiting");
        assert_eq!(item["payload"]["status"], "waiting");
    }

    /// The same journal fact must produce the same event id every time, or a resume
    /// would re-render the whole conversation on top of itself.
    #[test]
    fn replaying_the_same_event_yields_the_same_identity() {
        let mut projector = Projector::new();
        let first = run_item(&mut projector, "turn/accepted", 7, json!({"text": "hi"}));
        let again = run_item(&mut projector, "turn/accepted", 7, json!({"text": "hi"}));
        assert_eq!(first["event_id"], again["event_id"]);
        assert_eq!(first["payload"]["item_id"], again["payload"]["item_id"]);
    }

    /// Closing a turn must always be reported as a status change.
    ///
    /// An either/or that emitted the reply instead left the thread reading "running"
    /// after the run finished, so the composer offered Stop and refused the next
    /// send. The reply arrives on `model_completed`; this event is about the turn.
    #[test]
    fn closing_a_turn_always_reports_completion() {
        let mut projector = Projector::new();
        run_item(&mut projector, "turn/started", 1, json!({"turn_id": "t"}));
        let spoken = run_item(&mut projector, "turn/model_completed", 2, json!({"round": 0, "text": "hello"}));
        assert_eq!(spoken["payload"]["kind"], "message");
        let closing = run_item(&mut projector, "turn/completed", 3, json!({"text": "hello"}));
        assert_eq!(closing["payload"]["kind"], "status");
        assert_eq!(closing["payload"]["payload"]["status"], "completed");
    }

    /// Two closures in one reply must not share an identity.
    ///
    /// An expiry sweep reports events that never went through the journal, so they
    /// have no seq and the same envelope id. The client dedupes on `event_id`, and
    /// with a shared one it kept the first closure and silently ignored the rest.
    #[test]
    fn closures_without_a_journal_seq_stay_distinguishable() {
        let mut projector = Projector::new();
        let closure = |request: &str| {
            json!({
                "thread_id": "th",
                "seq": 0,
                "method": "item/approval_resolved",
                "event_id": "th:0",
                "created_at": "",
                "payload": {"request_id": request, "decision": "expired", "state": "ending"},
            })
        };
        let first = projector.project(&closure("r1")).expect("first closure");
        let second = projector.project(&closure("r2")).expect("second closure");
        assert_ne!(first["event_id"], second["event_id"]);
        assert_eq!(first["payload"]["payload"]["state"], "ending");
    }

    /// Internal bookkeeping never reaches the webview.
    #[test]
    fn internal_events_project_to_nothing() {
        let mut projector = Projector::new();
        assert!(projector.project(&envelope("turn/model_started", 1, json!({"round": 0}))).is_none());
        assert!(projector.project(&envelope("item/tool_replayed", 2, json!({}))).is_none());
    }
}
