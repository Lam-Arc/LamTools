//! The turn loop.
//!
//! Owns exactly four things: round budget, the cancel boundary, the approval
//! hand-off, and the tool stage transition. Storage details live in
//! `sunday-store`; model transport lives in `sunday-llm`; nothing here parses
//! HTTP or touches a file.

use std::collections::VecDeque;
use std::sync::Mutex;
use sunday_context::{Policy, Summarizer};
use sunday_protocol::{
    BudgetReason, CancelToken, CoreError, EventKind, HostKind, Message, Model, ModelDelta,
    ModelRequest, RunBudget, RunOutcome, Tool, ToolCall, ToolCtx, ToolSpec, WorkspaceId,
};
use sunday_store::{Continuation, Guidance, Store};

pub enum Approval {
    /// Policy already decided; run it.
    Auto,
    /// Stop and ask the user.
    Ask,
    /// The user said no.
    Deny { reason: String },
}

pub trait Approver: Send + Sync {
    fn decide(&self, call: &ToolCall, spec: &ToolSpec) -> Approval;
}

pub struct AutoApprove;
impl Approver for AutoApprove {
    fn decide(&self, _call: &ToolCall, _spec: &ToolSpec) -> Approval {
        Approval::Auto
    }
}

/// What the agent needs to decide *when* to compact. The policy itself lives in
/// `sunday-context`; the agent only checks the trigger and asks for compaction.
pub struct ContextPort<'a> {
    pub policy: Policy,
    pub summarizer: &'a dyn Summarizer,
}

pub struct Env<'a> {
    pub store: &'a Mutex<Store>,
    pub model: &'a dyn Model,
    pub tools: &'a [&'a dyn Tool],
    pub approver: &'a dyn Approver,
    /// The same token the host and the model client hold, so a Stop reaches all
    /// three. It replaces a bare `AtomicBool` because a token can be handed to
    /// an async HTTP request without the request having to know about the loop.
    pub cancel: &'a CancelToken,
    pub workspace: WorkspaceId,
    pub host: HostKind,
    /// `None` disables compaction entirely, which is what most tests want.
    pub context: Option<ContextPort<'a>>,
}

pub struct TurnInput {
    pub thread_id: String,
    pub turn_id: String,
    pub model_id: String,
    pub system: Option<String>,
    pub prompt: String,
}

/// What happened to one tool call.
enum Step {
    Done,
    Denied,
    NeedsApproval { approval_id: String },
    MustReconcile { tool_call_id: String },
}

impl<'a> Env<'a> {
    fn emit(&self, thread: &str, event_id: &str, kind: EventKind, payload: serde_json::Value) {
        let mut store = self.store.lock().unwrap();
        // Event ids are derived from durable state, so a replayed step cannot
        // insert a duplicate row.
        let _ = store.append_event(&self.workspace, thread, event_id, kind, payload);
    }

    /// Moves pending user instructions from the store into the message list.
    /// The event is written before the row is marked consumed, and the event id
    /// derives from the guidance id, so a crash between the two cannot double
    /// apply or silently drop an instruction.
    fn drain_guidance(&self, thread: &str) -> Result<Vec<Guidance>, CoreError> {
        let pending = {
            let store = self.store.lock().unwrap();
            store.pending_guidance(thread)?
        };
        if pending.is_empty() {
            return Ok(Vec::new());
        }
        for guidance in &pending {
            self.emit(
                thread,
                &format!("{thread}:guidance:{}", guidance.guidance_id),
                EventKind::GuidanceReceived,
                serde_json::json!({
                    "guidance_id": guidance.guidance_id,
                    "text": guidance.text,
                }),
            );
        }
        let ids: Vec<String> = pending.iter().map(|g| g.guidance_id.clone()).collect();
        {
            let mut store = self.store.lock().unwrap();
            store.consume_guidance(thread, &ids)?;
        }
        Ok(pending)
    }

    async fn execute(
        &self,
        thread: &str,
        call: &ToolCall,
        tools: &[&dyn Tool],
        pre_approved: bool,
    ) -> Result<Step, CoreError> {
        let Some(tool) = tools.iter().find(|t| t.spec().id == call.name) else {
            return Err(CoreError::UnsupportedCapability {
                capability: call.name.clone(),
            });
        };

        // Consent already recorded for this call: asking again would loop.
        let decision = if pre_approved {
            Approval::Auto
        } else {
            self.approver.decide(call, tool.spec())
        };

        match decision {
            Approval::Deny { reason } => {
                self.emit(
                    thread,
                    &format!("{thread}:{}:denied", call.id),
                    EventKind::ApprovalResolved,
                    serde_json::json!({"tool_call_id": call.id, "reason": reason}),
                );
                return Ok(Step::Denied);
            }
            Approval::Ask => {
                // The call is durable before the user is asked, so the approval
                // refers to something that exists.
                let prepared = {
                    let mut store = self.store.lock().unwrap();
                    store.prepare_tool_once(thread, call, tool.spec().side_effect)?
                };
                self.emit(
                    thread,
                    &format!("{thread}:{}:prepared", call.id),
                    EventKind::ToolPrepared,
                    serde_json::json!({"tool_call_id": call.id}),
                );
                if matches!(prepared, sunday_protocol::Prepared::MustReconcile) {
                    return Ok(Step::MustReconcile {
                        tool_call_id: call.id.clone(),
                    });
                }
                let approval = {
                    let mut store = self.store.lock().unwrap();
                    store.request_approval(thread, call, 300, now_epoch())?
                };
                self.emit(
                    thread,
                    &format!("{thread}:{}:approval", call.id),
                    EventKind::ApprovalRequested,
                    serde_json::json!({
                        "tool_call_id": call.id,
                        "approval_id": approval.approval_id,
                        "args_digest": approval.args_digest,
                    }),
                );
                return Ok(Step::NeedsApproval {
                    approval_id: approval.approval_id,
                });
            }
            Approval::Auto => {}
        }

        let prepared = {
            let mut store = self.store.lock().unwrap();
            store.prepare_tool_once(thread, call, tool.spec().side_effect)?
        };
        self.emit(
            thread,
            &format!("{thread}:{}:prepared", call.id),
            EventKind::ToolPrepared,
            serde_json::json!({"tool_call_id": call.id}),
        );
        match prepared {
            sunday_protocol::Prepared::AlreadyDone => {
                self.emit(
                    thread,
                    &format!("{thread}:{}:replayed", call.id),
                    EventKind::ToolReplayed,
                    serde_json::json!({"tool_call_id": call.id}),
                );
                return Ok(Step::Done);
            }
            sunday_protocol::Prepared::MustReconcile => {
                return Ok(Step::MustReconcile {
                    tool_call_id: call.id.clone(),
                });
            }
            sunday_protocol::Prepared::Ready => {}
        }

        {
            let mut store = self.store.lock().unwrap();
            store.mark_dispatched(&call.id)?;
        }
        self.emit(
            thread,
            &format!("{thread}:{}:dispatched", call.id),
            EventKind::ToolDispatched,
            serde_json::json!({"tool_call_id": call.id}),
        );

        let ctx = ToolCtx {
            thread_id: thread.to_owned(),
            host: Some(self.host),
        };
        let outcome = tool.execute(call.args.clone(), &ctx).await;
        let (payload, ok) = match &outcome {
            Ok(out) => (
                serde_json::json!({"content": out.content, "is_error": out.is_error}),
                !out.is_error,
            ),
            Err(err) => (serde_json::json!({"error": format!("{err}")}), false),
        };
        {
            let mut store = self.store.lock().unwrap();
            store.finish_tool_call(&call.id, &payload, ok)?;
        }
        self.emit(
            thread,
            &format!("{thread}:{}:result", call.id),
            if ok {
                EventKind::ToolSucceeded
            } else {
                EventKind::ToolFailed
            },
            serde_json::json!({"tool_call_id": call.id}),
        );
        Ok(Step::Done)
    }
}

fn now_epoch() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn tool_result_text(payload: &serde_json::Value) -> String {
    payload
        .get("content")
        .and_then(|v| v.as_str())
        .or_else(|| payload.get("error").and_then(|v| v.as_str()))
        .unwrap_or("(no result)")
        .to_owned()
}

pub async fn run_turn(
    env: &Env<'_>,
    input: TurnInput,
    budget: RunBudget,
) -> Result<RunOutcome, CoreError> {
    let mut messages = Vec::new();
    if let Some(system) = &input.system {
        messages.push(Message::System {
            content: system.clone(),
        });
    }
    messages.push(Message::User {
        content: input.prompt,
    });

    env.emit(
        &input.thread_id,
        &format!("{}:{}:started", input.turn_id, input.thread_id),
        EventKind::RunStarted,
        serde_json::json!({"turn_id": input.turn_id}),
    );

    drive(
        env,
        &input.thread_id,
        &input.turn_id,
        "start",
        &input.model_id,
        messages,
        budget,
    )
    .await
}

/// Resumes a turn that stopped for an approval, without calling the model again
/// for the pending decision.
pub async fn resume_turn(
    env: &Env<'_>,
    thread_id: &str,
    approval_id: &str,
    args_digest: &str,
    budget: RunBudget,
) -> Result<RunOutcome, CoreError> {
    let (continuation, pending) = {
        let mut store = env.store.lock().unwrap();
        store.respond_approval(approval_id, args_digest, now_epoch(), true)?;
        let continuation = store
            .load_continuation(thread_id)?
            .ok_or_else(|| CoreError::invalid(format!("no pending turn for {thread_id}")))?;
        let pending = store
            .pending_call(approval_id)?
            .ok_or_else(|| CoreError::invalid(format!("no call for approval {approval_id}")))?;
        (continuation, pending)
    };

    let call = pending.0;
    let mut messages = continuation.messages.clone();
    messages.push(Message::ToolResult {
        call_id: call.id.clone(),
        name: call.name.clone(),
        content: String::new(),
    });
    // Replace the placeholder above with the real result after executing.
    messages.pop();

    match env.execute(thread_id, &call, env.tools, true).await? {
        Step::MustReconcile { tool_call_id } => {
            return Ok(RunOutcome::WaitingForReconciliation {
                tool_call_id,
                hint: "a previous attempt was dispatched and its result is unknown".into(),
            })
        }
        Step::NeedsApproval { .. } => {
            return Err(CoreError::invalid("approval requested after approval"))
        }
        Step::Denied => {
            messages.push(Message::ToolResult {
                call_id: call.id.clone(),
                name: call.name.clone(),
                content: "denied".into(),
            });
        }
        Step::Done => {
            let payload = {
                let store = env.store.lock().unwrap();
                store.tool_result(&call.id)?
            }
            .unwrap_or(serde_json::json!({"content": "(no result)"}));
            messages.push(Message::ToolResult {
                call_id: call.id.clone(),
                name: call.name.clone(),
                content: tool_result_text(&payload),
            });
        }
    }

    env.emit(
        thread_id,
        &format!("{thread_id}:{}:resumed", continuation.turn_id),
        EventKind::RunStarted,
        serde_json::json!({"turn_id": continuation.turn_id, "resumed": true}),
    );

    drive(
        env,
        thread_id,
        &continuation.turn_id,
        "resume",
        &continuation.model_id,
        messages,
        budget,
    )
    .await
}

/// `phase` namespaces the event ids. A resumed turn restarts at round 0, and
/// without this its model events would reuse the first attempt's ids and be
/// silently dropped as duplicates.
async fn drive(
    env: &Env<'_>,
    thread: &str,
    turn_id: &str,
    phase: &str,
    model_id: &str,
    mut messages: Vec<Message>,
    budget: RunBudget,
) -> Result<RunOutcome, CoreError> {
    let visible = sunday_protocol::visible_tools(env.tools, env.host);
    let mut tool_calls_used = 0u32;

    let started = std::time::Instant::now();

    for round in 0..budget.max_rounds {
        if env.cancel.is_cancelled() {
            env.emit(
                thread,
                &format!("{thread}:{turn_id}:{phase}:{round}:cancelled"),
                EventKind::RunCancelled,
                serde_json::json!({}),
            );
            return Ok(RunOutcome::Cancelled);
        }
        if started.elapsed() > budget.wall_clock {
            return Ok(RunOutcome::BudgetExhausted {
                reason: BudgetReason::WallClock,
            });
        }

        // A user instruction that arrived while the previous round was running
        // takes effect here, before the model is asked again.
        for guidance in env.drain_guidance(thread)? {
            messages.push(Message::User {
                content: guidance.text,
            });
        }

        if let Some(context) = env.context.as_ref() {
            if sunday_context::needs_compaction(&messages, &context.policy) {
                if let Some(compaction) =
                    sunday_context::compact(&messages, &context.policy, context.summarizer)?
                {
                    messages = compaction.messages;
                    env.emit(
                        thread,
                        &format!("{thread}:{turn_id}:{phase}:{round}:compacted"),
                        EventKind::ContextCompacted,
                        serde_json::json!({
                            "removed_messages": compaction.removed_messages,
                            "summary_chars": compaction.summary_chars,
                        }),
                    );
                }
            }
        }

        env.emit(
            thread,
            &format!("{thread}:{turn_id}:{phase}:{round}:model"),
            EventKind::ModelStarted,
            serde_json::json!({"round": round}),
        );

        let mut streamed = String::new();
        let mut sink = |delta: ModelDelta| {
            if let ModelDelta::Text(text) = delta {
                streamed.push_str(&text);
            }
        };
        let turn = match env
            .model
            .stream(
                ModelRequest {
                    model_id: model_id.to_owned(),
                    messages: messages.clone(),
                    tools: visible.clone(),
                    temperature: None,
                    max_output_tokens: None,
                    // The same token the loop checks, so a Stop during the model
                    // call reaches the HTTP stream instead of waiting for the
                    // next round boundary.
                    cancel: env.cancel.clone(),
                },
                &mut sink,
            )
            .await
        {
            Ok(turn) => turn,
            Err(error) => {
                // A cancel is a normal outcome, not a failure the user should be
                // shown as an error. The turn stops where it is.
                if env.cancel.is_cancelled() {
                    env.emit(
                        thread,
                        &format!("{thread}:{turn_id}:{phase}:{round}:cancelled"),
                        EventKind::RunCancelled,
                        serde_json::json!({"reason": "model call cancelled"}),
                    );
                    return Ok(RunOutcome::Cancelled);
                }
                return Err(error);
            }
        };

        env.emit(
            thread,
            &format!("{thread}:{turn_id}:{phase}:{round}:model_done"),
            EventKind::ModelCompleted,
            serde_json::json!({}),
        );

        if turn.tool_calls.is_empty() {
            let text = turn.text.unwrap_or(streamed);
            env.emit(
                thread,
                &format!("{thread}:{turn_id}:{phase}:{round}:completed"),
                EventKind::RunCompleted,
                serde_json::json!({"text": text}),
            );
            let mut store = env.store.lock().unwrap();
            store.clear_continuation(thread)?;
            return Ok(RunOutcome::Completed { text });
        }

        messages.push(Message::AssistantToolCalls {
            calls: turn.tool_calls.clone(),
            content: turn.text.clone(),
        });

        for call in turn.tool_calls {
            // Invariant I8: after cancel no new tool call starts. Checked per
            // call, not once per round, because the model may return several and
            // the user may press Stop between them.
            if env.cancel.is_cancelled() {
                env.emit(
                    thread,
                    &format!("{thread}:{turn_id}:{phase}:{round}:cancelled"),
                    EventKind::RunCancelled,
                    serde_json::json!({"reason": "cancel before tool dispatch"}),
                );
                let mut store = env.store.lock().unwrap();
                store.clear_continuation(thread)?;
                return Ok(RunOutcome::Cancelled);
            }
            if tool_calls_used >= budget.max_tool_calls {
                return Ok(RunOutcome::BudgetExhausted {
                    reason: BudgetReason::ToolCalls,
                });
            }
            tool_calls_used += 1;

            match env.execute(thread, &call, env.tools, false).await? {
                Step::Done => {
                    let payload = {
                        let store = env.store.lock().unwrap();
                        store.tool_result(&call.id)?
                    }
                    .unwrap_or(serde_json::json!({"content": "(no result)"}));
                    messages.push(Message::ToolResult {
                        call_id: call.id.clone(),
                        name: call.name.clone(),
                        content: tool_result_text(&payload),
                    });
                }
                Step::Denied => {
                    messages.push(Message::ToolResult {
                        call_id: call.id.clone(),
                        name: call.name.clone(),
                        content: "denied by the user".into(),
                    });
                }
                Step::NeedsApproval { approval_id } => {
                    let mut store = env.store.lock().unwrap();
                    store.save_continuation(&Continuation {
                        thread_id: thread.to_owned(),
                        turn_id: turn_id.to_owned(),
                        model_id: model_id.to_owned(),
                        messages,
                        pending_call_id: Some(call.id.clone()),
                    })?;
                    return Ok(RunOutcome::NeedsApproval { approval_id });
                }
                Step::MustReconcile { tool_call_id } => {
                    env.emit(
                        thread,
                        &format!("{thread}:{}:unknown", call.id),
                        EventKind::RunWaitingForReconciliation,
                        serde_json::json!({"tool_call_id": call.id}),
                    );
                    let mut store = env.store.lock().unwrap();
                    store.save_continuation(&Continuation {
                        thread_id: thread.to_owned(),
                        turn_id: turn_id.to_owned(),
                        model_id: model_id.to_owned(),
                        messages,
                        pending_call_id: Some(call.id.clone()),
                    })?;
                    return Ok(RunOutcome::WaitingForReconciliation {
                        tool_call_id,
                        hint: "dispatched earlier, result unknown; reconcile before retrying"
                            .into(),
                    });
                }
            }
        }
    }

    Ok(RunOutcome::BudgetExhausted {
        reason: BudgetReason::Rounds,
    })
}

// ---------------------------------------------------------------- queue

/// One turn at a time per thread; the rest wait instead of being refused.
/// The old runtime refused concurrent runs, which turns a double tap on a phone
/// into a user-visible error.
#[derive(Default)]
pub struct ThreadQueue {
    queue: VecDeque<String>,
    running: Option<String>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum Submit {
    Started,
    Queued(usize),
    AlreadyRunning,
}

impl ThreadQueue {
    pub fn submit(&mut self, run_id: &str) -> Submit {
        if self.running.as_deref() == Some(run_id) {
            return Submit::AlreadyRunning;
        }
        match &self.running {
            None => {
                self.running = Some(run_id.to_owned());
                Submit::Started
            }
            Some(_) => {
                if !self.queue.iter().any(|id| id == run_id) {
                    self.queue.push_back(run_id.to_owned());
                }
                Submit::Queued(self.queue.len())
            }
        }
    }

    pub fn finish_current(&mut self) -> Option<String> {
        self.running = None;
        let next = self.queue.pop_front();
        if let Some(id) = &next {
            self.running = Some(id.clone());
        }
        next
    }

    pub fn cancel(&mut self, run_id: &str) -> bool {
        if self.running.as_deref() == Some(run_id) {
            self.running = None;
            return true;
        }
        match self.queue.iter().position(|id| id == run_id) {
            Some(index) => {
                self.queue.remove(index);
                true
            }
            None => false,
        }
    }

    pub fn running(&self) -> Option<&str> {
        self.running.as_deref()
    }

    pub fn pending(&self) -> usize {
        self.queue.len()
    }
}
