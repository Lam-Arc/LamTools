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
use sunday_host::app_server::iso_utc;

#[cfg(test)]
mod contract;

/// File artifacts a tool reported, in the shape the client renders.
///
/// The write tool answers with `{"ok": true, "path": ..., "bytes": ...}`; anything
/// that does not name a path produces nothing rather than an empty card.
fn artifacts_from_output(thread: &str, turn: &str, item_id: &str, output: &str) -> Vec<Value> {
    let Ok(parsed) = serde_json::from_str::<Value>(output) else {
        return Vec::new();
    };
    if parsed.get("ok").and_then(Value::as_bool) != Some(true) {
        return Vec::new();
    }
    let Some(path) = parsed.get("path").and_then(Value::as_str) else {
        return Vec::new();
    };
    if path.trim().is_empty() {
        return Vec::new();
    }
    let name = path.rsplit('/').next().unwrap_or(path);
    vec![json!({
        // Stable and readable: the same file written again by the same call is the
        // same artifact, so a resumed screen shows one card instead of two.
        "artifact_id": format!("{item_id}:artifact:{path}"),
        "thread_id": thread,
        "turn_id": turn,
        "item_id": item_id,
        "kind": "file",
        "name": name,
        "path": path,
        "uri": path,
        "size_bytes": parsed.get("bytes").cloned().unwrap_or(Value::Null),
        "metadata": { "description": "" },
    })]
}

/// Wall clock, in the unit `RunItemEvent.created_at_ms` is written in.
fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis() as u64)
        .unwrap_or(0)
}

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

    /// The row a tool call was given when it was prepared.
    ///
    /// Every later fact about that call belongs to the same row. Falling back to a
    /// freshly computed id is only correct for a call the host never saw prepared.
    fn row_of(&self, call: &str) -> Option<String> {
        self.calls
            .get(call)
            .and_then(|known| known.get("item_id"))
            .and_then(Value::as_str)
            .map(str::to_owned)
    }

    /// Projects one journal envelope, or `None` when it has no rendered meaning.
    pub fn project(&mut self, envelope: &Value) -> Option<Value> {
        let thread = envelope
            .get("thread_id")
            .and_then(Value::as_str)?
            .to_owned();
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
            // A closure is identified by whatever it is about: the approval it settles,
            // or the turn it closes. Without this, every recovery event in one reply
            // shared one id and the client kept only the first.
            let discriminant = envelope
                .get("payload")
                .and_then(|value| {
                    value
                        .get("request_id")
                        .or_else(|| value.get("approval_id"))
                        .or_else(|| value.get("turn_id"))
                })
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
        //
        // `item/approval_resolved` never inherits the active turn. The journal's own
        // answer event carries no turn id, and inheriting one put the answer after the
        // turn's completion while still naming that turn, so the client re-opened a run
        // that had already ended and the composer stayed on Stop. The row the answer
        // belongs to is remembered when the call is prepared, not derived from the turn.
        let turn = match payload.get("turn_id").and_then(Value::as_str) {
            Some(explicit) => explicit.to_owned(),
            None if method == "item/approval_resolved" => String::new(),
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
                    // A `userMessage` carries typed input parts, not a bare string
                    // (`selectors.ts`: "content is an array of typed input parts").
                    // The reader also accepts a string, but relying on that put the
                    // producer outside the contract the desktop core writes to.
                    json!({
                        "type": "userMessage",
                        "role": "user",
                        "content": [{ "type": "text", "text": content }],
                    }),
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
                // The row id is decided once, here, and reused by the approval card,
                // the dispatch and the result. Recomputing it later from that event's
                // own turn fails for a closure, which carries an empty turn on purpose
                // so it cannot revive one: the answer then landed on a second row and
                // the card the user had just answered stayed answerable.
                let row = tool_item(&call);
                self.calls.insert(
                    call.clone(),
                    json!({ "name": name, "arguments": args, "item_id": row }),
                );
                (
                    "tool_call",
                    row,
                    "waiting",
                    json!({
                        "type": "dynamicToolCall",
                        "tool_call_id": call,
                        "tool_name": name,
                        // `arguments` is what the client reads
                        // (`messageParts.ts`, `selectors.ts`, `workbenchProjection.ts`
                        // all check `item.arguments` first). `tool_args` stays as an
                        // alias for the one place that looks for it.
                        "arguments": args,
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
                    self.row_of(&call).unwrap_or_else(|| tool_item(&call)),
                    "waiting",
                    json!({
                        "type": "serverRequest",
                        "request_id": request,
                        "tool_call_id": call,
                        "kind": "approval",
                        "message": message,
                        "tool_name": tool_name,
                        "arguments": tool_args,
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
                // Field for field with the desktop core's decision lifecycle event
                // (`app/live/interactions.py`): the card vocabulary is
                // appearing/processing/ending, `turn_id` stays empty so a card can
                // never revive or close a turn, and the payload carries the request
                // lifecycle as `status` beside the bare `state`.
                let state = {
                    let declared = text("state");
                    if declared.is_empty() {
                        "ending".to_owned()
                    } else {
                        declared
                    }
                };
                // A closure without a call id settles a card, not a tool row: the resume
                // sweep reports what aged out, and those events carry a request id but no
                // tool call. Naming them after an empty call produced `thread:::tool`, a
                // single id that eight closures shared, so the transcript showed one row
                // where eight cards had been settled. The desktop core names a closure
                // after its request id.
                let item_id = if call.is_empty() {
                    request.clone()
                } else {
                    self.row_of(&call).unwrap_or_else(|| tool_item(&call))
                };
                (
                    "approval_response",
                    item_id,
                    "completed",
                    json!({
                        "type": "serverRequest",
                        "request_id": request,
                        "interaction_id": request,
                        "tool_call_id": call,
                        "decision": decision,
                        "action": decision,
                        "state": state,
                        "lifecycle": state,
                        "status": "resolved",
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
                    self.row_of(&call).unwrap_or_else(|| tool_item(&call)),
                    "running",
                    json!({
                        "type": "dynamicToolCall",
                        "tool_call_id": call,
                        "tool_name": known.get("name").cloned().unwrap_or(Value::Null),
                        "arguments": known.get("arguments").cloned().unwrap_or(Value::Null),
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
                    .or_else(|| {
                        payload
                            .get("error")
                            .and_then(Value::as_str)
                            .map(str::to_owned)
                    })
                    .unwrap_or_default();
                let failed = method == "item/failed"
                    || payload
                        .get("is_error")
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                // A tool that produced a file says so in its own output JSON. Turning
                // that into an artifact here is what lets the transcript show the file
                // card; the desktop core does the same from `_artifact_sources`
                // (`event/runtime_projection.py`), and the client already renders the
                // shape it produces.
                let row = self.row_of(&call).unwrap_or_else(|| tool_item(&call));
                let artifacts = artifacts_from_output(&thread, &turn, &row, &content);
                let result_status = if failed { "failed" } else { "completed" };
                let mut body = json!({
                    "type": "dynamicToolCall",
                    "tool_call_id": call,
                    "tool_name": known.get("name").cloned().unwrap_or(Value::Null),
                    // `content` is what this host has always sent and the tool row
                    // reads it first. `delta` / `tool_result` / `replace` are the
                    // desktop core's names (`runtime_projection.py:326`); sending
                    // both means neither reader has to know which core spoke.
                    "content": content,
                    "delta": content,
                    "tool_result": content,
                    "is_error": failed,
                    "replace": true,
                    "status": result_status,
                    "error": if failed {
                        json!(payload
                            .get("error")
                            .and_then(Value::as_str)
                            .unwrap_or("the tool failed"))
                    } else {
                        Value::Null
                    },
                });
                if !artifacts.is_empty() {
                    if let Some(object) = body.as_object_mut() {
                        object.insert("artifacts".into(), json!(artifacts));
                    }
                }
                ("tool_result", row, result_status, body)
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
                    // Mid-turn guidance is a user message too: same typed-part shape
                    // as `turn/accepted`, or the two producers disagree in one file.
                    json!({
                        "type": "userMessage",
                        "role": "user",
                        "content": [{ "type": "text", "text": content }],
                    }),
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
                body.get("request_id")
                    .and_then(Value::as_str)
                    .unwrap_or("?"),
                body.get("tool_call_id")
                    .and_then(Value::as_str)
                    .unwrap_or("?"),
            );
        }

        // Artifacts belong on the item, not inside its payload: `RunItemEvent.to_dict`
        // serializes them outside `payload`, and the client reads them there
        // (`store.ts`: "artifacts on the runItem event TOP level"). They are built in
        // the tool arm because only it knows what the tool said it wrote.
        let mut body = body;
        let artifacts = match body
            .as_object_mut()
            .and_then(|object| object.remove("artifacts"))
        {
            Some(Value::Array(items)) if !items.is_empty() => items,
            _ => Vec::new(),
        };

        // The journal's own instant when the frame carries one: `respond` replays the
        // journal, and a replayed fact has to show when it happened rather than when it
        // was replayed. Without a time on the frame this host is stamping a fact it has
        // just observed itself.
        let created_at_ms = envelope
            .get("created_at_ms")
            .and_then(Value::as_i64)
            .filter(|ms| *ms > 0)
            .unwrap_or_else(|| now_ms() as i64);
        let mut item = serde_json::Map::new();
        item.insert("kind".into(), json!(kind));
        item.insert("thread_id".into(), json!(thread));
        item.insert("event_id".into(), json!(event_id));
        item.insert("status".into(), json!(status));
        item.insert("payload".into(), body);
        item.insert("created_at_ms".into(), json!(created_at_ms));
        // `to_dict` omits a field that carries nothing. Identity and ownership are
        // facts, so they stay even when the turn id is the explicit empty string that
        // keeps a closure off its finished turn.
        item.insert("turn_id".into(), json!(turn));
        item.insert("item_id".into(), json!(item_id));
        if !artifacts.is_empty() {
            item.insert("artifacts".into(), Value::Array(artifacts));
        }
        if seq > 0 {
            item.insert("seq".into(), json!(seq));
        }

        let mut envelope = serde_json::Map::new();
        envelope.insert("method".into(), json!("core/runItem"));
        envelope.insert("thread_id".into(), json!(thread));
        envelope.insert("event_id".into(), json!(event_id));
        // A real timestamp, never "". The client stores this string verbatim and
        // formats it; an empty one is a valid string holding an invalid date.
        envelope.insert("created_at".into(), json!(iso_utc(created_at_ms)));
        envelope.insert("turn_id".into(), json!(turn));
        envelope.insert("item_id".into(), json!(item_id));
        // seq = 0 means "no persisted anchor". Writing the 0 makes the client treat
        // it as a real position and sort the item before every journal event
        // (`event_store.py::AppEventEnvelope.to_dict` omits it for the same reason).
        if seq > 0 {
            envelope.insert("seq".into(), json!(seq));
        }
        envelope.insert("payload".into(), Value::Object(item));
        Some(Value::Object(envelope))
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
        let item = run_item(
            &mut projector,
            "turn/accepted",
            1,
            json!({"kind": "turn_start", "text": "make notes.md"}),
        );
        assert_eq!(item["method"], "core/runItem");
        assert_eq!(item["payload"]["kind"], "message");
        assert_eq!(item["payload"]["payload"]["role"], "user");
        assert_eq!(
            item["payload"]["payload"]["content"],
            json!([{ "type": "text", "text": "make notes.md" }]),
            "a userMessage carries typed input parts, not a bare string"
        );
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
        run_item(
            &mut projector,
            "turn/started",
            2,
            json!({"turn_id": "turn-1"}),
        );
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
        let call = run_item(
            &mut projector,
            "item/tool_prepared",
            2,
            json!({"tool_call_id": "c1", "name": "write_file", "arguments": {}}),
        );
        let done = run_item(
            &mut projector,
            "item/completed",
            3,
            json!({"tool_call_id": "c1", "content": "wrote 3 lines"}),
        );
        assert_eq!(done["payload"]["item_id"], call["payload"]["item_id"]);
        assert_eq!(done["payload"]["kind"], "tool_result");
        assert_eq!(done["payload"]["status"], "completed");
        assert_eq!(done["payload"]["payload"]["content"], "wrote 3 lines");

        let failed = run_item(
            &mut projector,
            "item/failed",
            4,
            json!({"tool_call_id": "c1", "error": "permission denied"}),
        );
        assert_eq!(failed["payload"]["status"], "failed");
    }

    /// Waiting for a human is not completion. Marking the turn done here would tell
    /// the user the task finished while a side effect is still unknown.
    #[test]
    fn waiting_for_reconciliation_is_not_a_completion() {
        let mut projector = Projector::new();
        run_item(&mut projector, "turn/started", 1, json!({"turn_id": "t"}));
        let item = run_item(
            &mut projector,
            "turn/waiting_for_reconciliation",
            2,
            json!({}),
        );
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
        let spoken = run_item(
            &mut projector,
            "turn/model_completed",
            2,
            json!({"round": 0, "text": "hello"}),
        );
        assert_eq!(spoken["payload"]["kind"], "message");
        let closing = run_item(
            &mut projector,
            "turn/completed",
            3,
            json!({"text": "hello"}),
        );
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

    /// The closure payload must match the desktop core's decision lifecycle event.
    ///
    /// `core/ui/src/appServer/store.ts` closes a card on `state: "ending"` and reads
    /// the request lifecycle from `status`; the desktop core writes both, plus an
    /// empty `turn_id` so a card transition cannot touch a turn. Anything missing
    /// here shows up as a card that stays open, or a turn that reopens.
    #[test]
    fn a_closure_carries_the_decision_lifecycle_fields() {
        let mut projector = Projector::new();
        let closure = json!({
            "thread_id": "th",
            "seq": 9,
            "method": "item/approval_resolved",
            "event_id": "th:9",
            "created_at": "",
            "payload": {"request_id": "r1", "decision": "deny"},
        });
        let item = projector.project(&closure).expect("closure");
        assert_eq!(item["payload"]["kind"], "approval_response");
        let body = &item["payload"]["payload"];
        assert_eq!(body["state"], "ending", "the card only closes on 'ending'");
        assert_eq!(body["lifecycle"], "ending");
        assert_eq!(body["status"], "resolved");
        assert_eq!(body["action"], "deny");
        assert_eq!(body["interaction_id"], "r1");
    }

    /// Recovery closes several turns in one reply; each must be distinguishable.
    #[test]
    fn recovery_closures_are_identified_by_their_turn() {
        let mut projector = Projector::new();
        let closure = |turn: &str| {
            json!({
                "thread_id": "th",
                "seq": 0,
                "method": "turn/completed",
                "event_id": "th:0",
                "created_at": "",
                "payload": {"text": "", "recovered": true, "turn_id": turn},
            })
        };
        let first = projector.project(&closure("turn-a")).expect("a");
        let second = projector.project(&closure("turn-b")).expect("b");
        assert_ne!(first["event_id"], second["event_id"]);
        assert_eq!(first["payload"]["turn_id"], "turn-a");
        assert_eq!(first["payload"]["payload"]["status"], "completed");
    }

    /// A write that succeeded must surface its file, not only a line of text.
    #[test]
    fn a_written_file_becomes_an_artifact() {
        let mut projector = Projector::new();
        run_item(&mut projector, "turn/started", 1, json!({"turn_id": "t"}));
        let done = run_item(
            &mut projector,
            "item/completed",
            2,
            json!({
                "tool_call_id": "c1",
                "content": r#"{"ok":true,"path":"notes.md","etag":"x","bytes":22}"#,
            }),
        );
        // Top level, where the core puts them and the client looks for them.
        let artifacts = &done["payload"]["artifacts"];
        assert_eq!(artifacts[0]["name"], "notes.md");
        assert_eq!(artifacts[0]["size_bytes"], 22);
        assert_eq!(artifacts[0]["item_id"], "th:t:c1:tool");
        assert!(
            done["payload"]["payload"]["artifacts"].is_null(),
            "an artifact inside the payload is a second copy the client ignores"
        );
    }

    /// Internal bookkeeping never reaches the webview.
    #[test]
    fn internal_events_project_to_nothing() {
        let mut projector = Projector::new();
        assert!(projector
            .project(&envelope("turn/model_started", 1, json!({"round": 0})))
            .is_none());
        assert!(projector
            .project(&envelope("item/tool_replayed", 2, json!({})))
            .is_none());
    }
}
