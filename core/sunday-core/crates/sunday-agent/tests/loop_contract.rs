//! Behaviour tests for the turn loop, against the real store.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use sunday_agent::{
    resume_turn, run_turn, Approval, Approver, AutoApprove, Env, ThreadQueue, TurnInput,
};
use sunday_protocol::{
    BudgetReason, CoreError, EventKind, HostKind, Model, ModelDelta, ModelRequest, ModelTurn,
    Permission, RunBudget, RunOutcome, SideEffect, Tool, ToolCall, ToolCtx, ToolOutput, ToolSpec,
};
use sunday_store::Store;

const WS: &str = "ws";

struct ScriptedModel {
    turns: Mutex<Vec<ModelTurn>>,
}

impl ScriptedModel {
    fn new(turns: Vec<ModelTurn>) -> Self {
        Self {
            turns: Mutex::new(turns),
        }
    }
}

#[async_trait::async_trait]
impl Model for ScriptedModel {
    async fn stream(
        &self,
        _request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError> {
        let turn = self.turns.lock().unwrap().remove(0);
        if let Some(text) = &turn.text {
            sink(ModelDelta::Text(text.clone()));
        }
        Ok(turn)
    }
}

struct CountingTool {
    spec: ToolSpec,
    runs: Arc<AtomicUsize>,
    fail: bool,
}

impl CountingTool {
    fn new(id: &str, side: SideEffect, runs: Arc<AtomicUsize>) -> Self {
        Self {
            spec: ToolSpec {
                id: id.into(),
                description: id.into(),
                input_schema: serde_json::json!({"type": "object"}),
                side_effect: side,
                hosts: vec![HostKind::Windows, HostKind::Android],
                permission: Permission::AutoAllow,
            },
            runs,
            fail: false,
        }
    }
}

#[async_trait::async_trait]
impl Tool for CountingTool {
    fn spec(&self) -> &ToolSpec {
        &self.spec
    }
    async fn execute(
        &self,
        _args: serde_json::Value,
        _ctx: &ToolCtx,
    ) -> Result<ToolOutput, CoreError> {
        self.runs.fetch_add(1, Ordering::SeqCst);
        if self.fail {
            return Err(CoreError::model("tool exploded"));
        }
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

fn call(id: &str, name: &str) -> ToolCall {
    ToolCall {
        id: id.into(),
        name: name.into(),
        args: serde_json::json!({"path": "a.txt"}),
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
        prompt: "do it".into(),
    }
}

fn budget(rounds: u32, calls: u32) -> RunBudget {
    RunBudget {
        max_rounds: rounds,
        max_tool_calls: calls,
        wall_clock: std::time::Duration::from_secs(30),
    }
}

// ---------------------------------------------------------------- happy path

#[tokio::test]
async fn a_complete_turn_writes_an_ordered_journal() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    let model = ScriptedModel::new(vec![turn_calling("c1", "write_file"), turn_text("done")]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("write_file", SideEffect::NonIdempotent, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);

    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };
    let outcome = run_turn(&env, input("t1"), budget(4, 8)).await.unwrap();

    assert_eq!(
        outcome,
        RunOutcome::Completed {
            text: "done".into()
        }
    );
    assert_eq!(runs.load(Ordering::SeqCst), 1);

    let kinds: Vec<EventKind> = store
        .lock()
        .unwrap()
        .events("t1", 0)
        .unwrap()
        .into_iter()
        .map(|e| e.kind)
        .collect();
    assert_eq!(
        kinds,
        vec![
            EventKind::RunStarted,
            EventKind::ModelStarted,
            EventKind::ModelCompleted,
            EventKind::ToolPrepared,
            EventKind::ToolDispatched,
            EventKind::ToolSucceeded,
            EventKind::ModelStarted,
            EventKind::ModelCompleted,
            EventKind::RunCompleted,
        ]
    );
    let seqs: Vec<u64> = store
        .lock()
        .unwrap()
        .events("t1", 0)
        .unwrap()
        .iter()
        .map(|e| e.seq)
        .collect();
    assert_eq!(seqs, (1..=9).collect::<Vec<u64>>());
}

// ---------------------------------------------------------------- A1 budget

#[tokio::test]
async fn a1_the_round_budget_stops_a_model_that_never_finishes() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    let model = ScriptedModel::new(vec![
        turn_calling("r1", "ping"),
        turn_calling("r2", "ping"),
        turn_calling("r3", "ping"),
    ]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("ping", SideEffect::Pure, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(&env, input("t1"), budget(2, 8)).await.unwrap();
    assert_eq!(
        outcome,
        RunOutcome::BudgetExhausted {
            reason: BudgetReason::Rounds
        }
    );
    assert_eq!(runs.load(Ordering::SeqCst), 2);
}

#[tokio::test]
async fn a1b_the_tool_call_budget_is_enforced_separately() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    let model = ScriptedModel::new(vec![ModelTurn {
        text: Some("two calls".into()),
        reasoning: None,
        tool_calls: vec![call("a", "ping"), call("b", "ping")],
        usage: None,
        provider_state: None,
    }]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("ping", SideEffect::Pure, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(&env, input("t1"), budget(4, 1)).await.unwrap();
    assert_eq!(
        outcome,
        RunOutcome::BudgetExhausted {
            reason: BudgetReason::ToolCalls
        }
    );
    assert_eq!(runs.load(Ordering::SeqCst), 1);
}

// ---------------------------------------------------------------- A2 cancel

#[tokio::test]
async fn a2_a_cancelled_turn_runs_no_tool_at_all() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    let model = ScriptedModel::new(vec![turn_calling("c1", "write_file")]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("write_file", SideEffect::NonIdempotent, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(true);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(&env, input("t1"), budget(4, 8)).await.unwrap();
    assert_eq!(outcome, RunOutcome::Cancelled);
    assert_eq!(runs.load(Ordering::SeqCst), 0);
    let kinds: Vec<EventKind> = store
        .lock()
        .unwrap()
        .events("t1", 0)
        .unwrap()
        .into_iter()
        .map(|e| e.kind)
        .collect();
    assert_eq!(kinds, vec![EventKind::RunStarted, EventKind::RunCancelled]);
}

// ---------------------------------------------------------------- approval

#[tokio::test]
async fn a3_an_approval_stops_the_turn_and_resuming_finishes_it_without_replaying() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    // The model is asked once for the call and once after the tool result.
    let model = ScriptedModel::new(vec![
        turn_calling("c1", "write_file"),
        turn_text("all done"),
    ]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("write_file", SideEffect::NonIdempotent, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AskApprover,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(&env, input("t1"), budget(4, 8)).await.unwrap();
    let approval_id = match outcome {
        RunOutcome::NeedsApproval { approval_id } => approval_id,
        other => panic!("expected an approval request, got {other:?}"),
    };
    assert_eq!(
        runs.load(Ordering::SeqCst),
        0,
        "nothing runs before consent"
    );

    let digest = store
        .lock()
        .unwrap()
        .pending_call(&approval_id)
        .unwrap()
        .expect("the pending call is durable")
        .1;

    let outcome = resume_turn(&env, "t1", &approval_id, &digest, budget(4, 8))
        .await
        .unwrap();
    assert_eq!(
        outcome,
        RunOutcome::Completed {
            text: "all done".into()
        }
    );
    assert_eq!(runs.load(Ordering::SeqCst), 1, "the tool runs exactly once");

    let events = store.lock().unwrap().events("t1", 0).unwrap();
    let approvals: Vec<&sunday_protocol::Event> = events
        .iter()
        .filter(|e| e.kind == EventKind::ApprovalRequested)
        .collect();
    assert_eq!(approvals.len(), 1, "the approval is recorded once");
    assert!(store
        .lock()
        .unwrap()
        .load_continuation("t1")
        .unwrap()
        .is_none());
}

#[tokio::test]
async fn a3b_resuming_with_a_tampered_digest_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    let model = ScriptedModel::new(vec![turn_calling("c1", "write_file"), turn_text("done")]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("write_file", SideEffect::NonIdempotent, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AskApprover,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let RunOutcome::NeedsApproval { approval_id } =
        run_turn(&env, input("t1"), budget(4, 8)).await.unwrap()
    else {
        panic!("expected approval")
    };

    let err = resume_turn(&env, "t1", &approval_id, "not-the-digest", budget(4, 8))
        .await
        .unwrap_err();
    assert!(
        matches!(err, CoreError::ApprovalArgsMismatch { .. }),
        "got {err:?}"
    );
    assert_eq!(runs.load(Ordering::SeqCst), 0);
}

// ---------------------------------------------------------------- A4 unknown

#[tokio::test]
async fn a4_an_unknown_outcome_stops_the_turn_and_never_retries() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("c.db");
    {
        // A previous run dispatched this call and died before recording a result.
        let mut store = Store::open(&path).unwrap();
        let c = call("c1", "write_file");
        store
            .prepare_tool_once("t1", &c, SideEffect::NonIdempotent)
            .unwrap();
        store.mark_dispatched("c1").unwrap();
        store.recover().unwrap();
    }

    let store = Mutex::new(Store::open(&path).unwrap());
    let model = ScriptedModel::new(vec![turn_calling("c1", "write_file"), turn_text("never")]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("write_file", SideEffect::NonIdempotent, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(&env, input("t1"), budget(4, 8)).await.unwrap();
    match outcome {
        RunOutcome::WaitingForReconciliation { tool_call_id, .. } => {
            assert_eq!(tool_call_id, "c1")
        }
        other => panic!("expected reconciliation, got {other:?}"),
    }
    assert_eq!(
        runs.load(Ordering::SeqCst),
        0,
        "an unknown effect must not rerun"
    );
}

// ---------------------------------------------------------------- A5 queue

#[test]
fn a5_a_second_run_queues_instead_of_being_refused() {
    let mut queue = ThreadQueue::default();
    assert_eq!(queue.submit("r1"), sunday_agent::Submit::Started);
    assert_eq!(queue.submit("r2"), sunday_agent::Submit::Queued(1));
    assert_eq!(queue.submit("r3"), sunday_agent::Submit::Queued(2));
    // A repeated submit of the same run must not enqueue it twice.
    assert_eq!(queue.submit("r2"), sunday_agent::Submit::Queued(2));

    assert!(queue.cancel("r3"));
    assert_eq!(queue.finish_current(), Some("r2".to_owned()));
    assert_eq!(queue.finish_current(), None);
    assert_eq!(queue.running(), None);
}

#[test]
fn a5b_submitting_the_running_run_is_a_noop() {
    let mut queue = ThreadQueue::default();
    assert_eq!(queue.submit("r1"), sunday_agent::Submit::Started);
    assert_eq!(queue.submit("r1"), sunday_agent::Submit::AlreadyRunning);
    assert_eq!(queue.pending(), 0);
}

// ---------------------------------------------------------------- A3 tool failure

#[tokio::test]
async fn a_failing_tool_is_recorded_as_failed_and_the_turn_continues() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    let model = ScriptedModel::new(vec![turn_calling("c1", "boom"), turn_text("recovered")]);
    let runs = Arc::new(AtomicUsize::new(0));
    let mut tool = CountingTool::new("boom", SideEffect::Pure, runs.clone());
    tool.fail = true;
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let outcome = run_turn(&env, input("t1"), budget(4, 8)).await.unwrap();
    assert_eq!(
        outcome,
        RunOutcome::Completed {
            text: "recovered".into()
        }
    );
    let events = store.lock().unwrap().events("t1", 0).unwrap();
    assert!(events.iter().any(|e| e.kind == EventKind::ToolFailed));
    assert!(!events.iter().any(|e| e.kind == EventKind::ToolSucceeded));
}

#[tokio::test]
async fn an_unknown_tool_name_is_refused_before_anything_runs() {
    let dir = tempfile::tempdir().unwrap();
    let store = Mutex::new(Store::open(dir.path().join("c.db")).unwrap());
    let model = ScriptedModel::new(vec![turn_calling("c1", "not_a_tool")]);
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = CountingTool::new("real_tool", SideEffect::Pure, runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];
    let cancel = AtomicBool::new(false);
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &AutoApprove,
        cancel: &cancel,
        workspace: WS.into(),
        host: HostKind::Windows,
        context: None,
    };

    let err = run_turn(&env, input("t1"), budget(4, 8)).await.unwrap_err();
    assert!(
        matches!(err, CoreError::UnsupportedCapability { .. }),
        "got {err:?}"
    );
}
