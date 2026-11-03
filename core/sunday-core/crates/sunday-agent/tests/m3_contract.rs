//! M3 behaviour: steer, compaction, wall clock, approval plus steer concurrency.
//!
//! The model here is scripted, but everything it touches is real: a real SQLite
//! file, the real loop, the real store. Guidance is injected from inside the
//! model call, which is exactly when a user would type.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use sunday_agent::{
    resume_turn, run_turn, Approval, Approver, AutoApprove, ContextPort, Env, TurnInput,
};
use sunday_context::{Policy, Summarizer};
use sunday_protocol::{
    BudgetReason, CoreError, EventKind, HostKind, Message, Model, ModelDelta, ModelRequest,
    ModelTurn, Permission, RunBudget, RunOutcome, SideEffect, Tool, ToolCall, ToolCtx, ToolOutput,
    ToolSpec,
};
use sunday_store::Store;

const WS: &str = "ws";

struct Scripted {
    turns: Mutex<Vec<ModelTurn>>,
    seen: Mutex<Vec<ModelRequest>>,
    store: Option<Arc<Mutex<Store>>>,
    inject_after_call: Option<(usize, String)>,
    delay_ms: u64,
    calls: AtomicUsize,
}

impl Scripted {
    fn new(turns: Vec<ModelTurn>) -> Self {
        Self {
            turns: Mutex::new(turns),
            seen: Mutex::new(Vec::new()),
            store: None,
            inject_after_call: None,
            delay_ms: 0,
            calls: AtomicUsize::new(0),
        }
    }

    fn with_store(mut self, store: Arc<Mutex<Store>>) -> Self {
        self.store = Some(store);
        self
    }

    /// Injects guidance while the model call is in flight.
    fn injecting(mut self, after_call: usize, text: &str) -> Self {
        self.inject_after_call = Some((after_call, text.to_owned()));
        self
    }

    fn with_delay(mut self, ms: u64) -> Self {
        self.delay_ms = ms;
        self
    }

    fn requests(&self) -> Vec<ModelRequest> {
        self.seen.lock().unwrap().clone()
    }
}

#[async_trait::async_trait]
impl Model for Scripted {
    async fn stream(
        &self,
        request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError> {
        let index = self.calls.fetch_add(1, Ordering::SeqCst);
        self.seen.lock().unwrap().push(request);
        if self.delay_ms > 0 {
            tokio::time::sleep(std::time::Duration::from_millis(self.delay_ms)).await;
        }
        if let Some((after, text)) = &self.inject_after_call {
            if *after == index {
                if let Some(store) = &self.store {
                    let mut store = store.lock().unwrap();
                    store
                        .append_guidance("t1", &format!("g{index}"), text)
                        .unwrap();
                }
            }
        }
        let turn = self.turns.lock().unwrap().remove(0);
        if let Some(text) = &turn.text {
            sink(ModelDelta::Text(text.clone()));
        }
        Ok(turn)
    }
}

struct Counting {
    spec: ToolSpec,
    runs: Arc<AtomicUsize>,
}

impl Counting {
    fn new(id: &str, runs: Arc<AtomicUsize>) -> Self {
        Self {
            spec: ToolSpec {
                id: id.into(),
                description: id.into(),
                input_schema: serde_json::json!({"type": "object"}),
                side_effect: SideEffect::NonIdempotent,
                hosts: vec![HostKind::Windows, HostKind::Android],
                permission: Permission::AutoAllow,
            },
            runs,
        }
    }
}

#[async_trait::async_trait]
impl Tool for Counting {
    fn spec(&self) -> &ToolSpec {
        &self.spec
    }
    async fn execute(&self, _a: serde_json::Value, _c: &ToolCtx) -> Result<ToolOutput, CoreError> {
        self.runs.fetch_add(1, Ordering::SeqCst);
        Ok(ToolOutput {
            content: "ok".into(),
            is_error: false,
        })
    }
}

struct AskApprover;
impl Approver for AskApprover {
    fn decide(&self, _call: &ToolCall, _spec: &ToolSpec) -> Approval {
        Approval::Ask
    }
}

struct Fixed(String);
impl Summarizer for Fixed {
    fn summarize(&self, dropped: &[Message]) -> Result<String, CoreError> {
        Ok(format!(
            "{}: {} earlier messages, condensed",
            self.0,
            dropped.len()
        ))
    }
}

fn call(id: &str, name: &str) -> ToolCall {
    ToolCall {
        id: id.into(),
        name: name.into(),
        args: serde_json::json!({}),
    }
}

fn turn_calling(id: &str, name: &str) -> ModelTurn {
    ModelTurn {
        text: Some("working".into()),
        reasoning: None,
        tool_calls: vec![call(id, name)],
        usage: None,
        provider_state: None,
    }
}

fn turn_text(text: &str) -> ModelTurn {
    ModelTurn {
        text: Some(text.into()),
        reasoning: None,
        tool_calls: vec![],
        usage: None,
        provider_state: None,
    }
}

fn input(thread: &str) -> TurnInput {
    TurnInput {
        thread_id: thread.into(),
        turn_id: "turn-1".into(),
        model_id: "m".into(),
        system: Some("be careful".into()),
        prompt: "do the thing".into(),
    }
}

fn budget(rounds: u32) -> RunBudget {
    RunBudget {
        max_rounds: rounds,
        max_tool_calls: 16,
        wall_clock: std::time::Duration::from_secs(30),
    }
}

// ---------------------------------------------------------------- steer

#[tokio::test]
async fn a_steer_written_during_a_model_call_takes_effect_next_round() {
    let dir = tempfile::tempdir().unwrap();
    let shared = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = Counting::new("write_file", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];

    // The user types while the first model call is in flight.
    let model = Scripted::new(vec![turn_calling("c1", "write_file"), turn_text("done")])
        .with_store(shared.clone())
        .injecting(0, "actually use b.txt");

    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &shared,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(&env, input("t1"), budget(4)).await.unwrap();
    assert_eq!(
        outcome,
        RunOutcome::Completed {
            text: "done".into()
        }
    );

    // The second model call must have seen the instruction.
    let requests = model.requests();
    assert_eq!(requests.len(), 2);
    let second = &requests[1];
    assert!(
        second.messages.iter().any(|m| matches!(
            m,
            Message::User { content } if content.contains("actually use b.txt")
        )),
        "the steer never reached the model: {:?}",
        second.messages
    );

    // Exactly one guidance event, and the row is consumed.
    let store = shared.lock().unwrap();
    let events = store.events("t1", 0).unwrap();
    let guidance: Vec<_> = events
        .iter()
        .filter(|e| e.kind == EventKind::GuidanceReceived)
        .collect();
    assert_eq!(guidance.len(), 1);
    assert!(store.pending_guidance("t1").unwrap().is_empty());
}

#[tokio::test]
async fn the_same_guidance_id_is_only_applied_once() {
    let dir = tempfile::tempdir().unwrap();
    let shared = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    {
        let mut store = shared.lock().unwrap();
        assert!(store.append_guidance("t1", "g1", "hello").unwrap());
        // A retried transport must not duplicate the instruction.
        assert!(!store.append_guidance("t1", "g1", "hello").unwrap());
        assert_eq!(store.pending_guidance("t1").unwrap().len(), 1);
    }
}

// ------------------------------------------------- approval plus steer

#[tokio::test]
async fn a_steer_written_while_an_approval_is_pending_survives_the_resume() {
    let dir = tempfile::tempdir().unwrap();
    let shared = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = Counting::new("write_file", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let model = Scripted::new(vec![
        turn_calling("c1", "write_file"),
        turn_text("finished"),
    ]);
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &shared,
        model: &model,
        tools: &tools,
        approver: &AskApprover,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let approval_id = match run_turn(&env, input("t1"), budget(4)).await.unwrap() {
        RunOutcome::NeedsApproval { approval_id } => approval_id,
        other => panic!("expected approval, got {other:?}"),
    };
    assert_eq!(runs.load(Ordering::SeqCst), 0);

    // The user answers the approval and types something at the same time.
    {
        let mut store = shared.lock().unwrap();
        store
            .append_guidance("t1", "g-during-approval", "then also check the log")
            .unwrap();
    }

    let digest = shared
        .lock()
        .unwrap()
        .pending_call(&approval_id)
        .unwrap()
        .unwrap()
        .1;
    let outcome = resume_turn(&env, "t1", &approval_id, &digest, budget(4))
        .await
        .unwrap();
    assert_eq!(
        outcome,
        RunOutcome::Completed {
            text: "finished".into()
        }
    );
    assert_eq!(
        runs.load(Ordering::SeqCst),
        1,
        "the approved call runs once"
    );

    let requests = model.requests();
    let last = requests.last().unwrap();
    assert!(
        last.messages.iter().any(|m| matches!(
            m,
            Message::User { content } if content.contains("then also check the log")
        )),
        "the steer written during the approval was lost"
    );
    assert!(shared
        .lock()
        .unwrap()
        .pending_guidance("t1")
        .unwrap()
        .is_empty());
}

// ---------------------------------------------------------------- compaction

#[tokio::test]
async fn compaction_runs_when_over_budget_and_the_turn_continues() {
    let dir = tempfile::tempdir().unwrap();
    let shared = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = Counting::new("write_file", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    // Four rounds so the message list grows past a tiny trigger.
    let model = Scripted::new(vec![
        turn_calling("c1", "write_file"),
        turn_calling("c2", "write_file"),
        turn_calling("c3", "write_file"),
        turn_text("finally done"),
    ]);
    let cancel = AtomicBool::new(false);
    let policy = Policy {
        trigger_tokens: 20,
        keep_recent: 2,
        max_summary_chars: 200,
    };
    let summarizer = Fixed(String::new());
    let env = Env {
        store: &shared,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: Some(ContextPort {
            policy,
            summarizer: &summarizer,
        }),
    };

    let outcome = run_turn(&env, input("t1"), budget(6)).await.unwrap();
    assert_eq!(
        outcome,
        RunOutcome::Completed {
            text: "finally done".into()
        }
    );

    let events = shared.lock().unwrap().events("t1", 0).unwrap();
    let compacted = events
        .iter()
        .filter(|e| e.kind == EventKind::ContextCompacted)
        .count();
    assert!(compacted >= 1, "compaction never triggered");

    // The model must have been handed a summary, and still the system prompt.
    let requests = model.requests();
    let last = requests.last().unwrap();
    assert!(matches!(
        last.messages.first(),
        Some(Message::System { .. })
    ));
    assert!(
        last.messages.iter().any(|m| match m {
            Message::System { content } | Message::User { content } =>
                content.contains("Summary of the earlier conversation"),
            _ => false,
        }),
        "no summary reached the model"
    );
    // And compaction must not have thrown away the work that already happened.
    assert_eq!(runs.load(Ordering::SeqCst), 3);
}

#[tokio::test]
async fn compaction_stays_off_when_the_budget_is_not_threatened() {
    let dir = tempfile::tempdir().unwrap();
    let shared = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    let model = Scripted::new(vec![turn_text("short")]);
    let tools: Vec<&dyn Tool> = vec![];
    let cancel = AtomicBool::new(false);
    let summarizer = Fixed(String::new());
    let env = Env {
        store: &shared,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: Some(ContextPort {
            policy: Policy::default(),
            summarizer: &summarizer,
        }),
    };
    run_turn(&env, input("t1"), budget(2)).await.unwrap();
    let events = shared.lock().unwrap().events("t1", 0).unwrap();
    assert!(!events.iter().any(|e| e.kind == EventKind::ContextCompacted));
}

// ---------------------------------------------------------------- wall clock

#[tokio::test]
async fn a_slow_model_is_stopped_by_the_wall_clock_budget() {
    let dir = tempfile::tempdir().unwrap();
    let shared = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = Counting::new("write_file", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let model = Scripted::new(vec![
        turn_calling("c1", "write_file"),
        turn_calling("c2", "write_file"),
        turn_calling("c3", "write_file"),
    ])
    .with_delay(20);
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &shared,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(
        &env,
        input("t1"),
        RunBudget {
            max_rounds: 10,
            max_tool_calls: 10,
            wall_clock: std::time::Duration::from_millis(1),
        },
    )
    .await
    .unwrap();

    assert_eq!(
        outcome,
        RunOutcome::BudgetExhausted {
            reason: BudgetReason::WallClock
        }
    );
}
