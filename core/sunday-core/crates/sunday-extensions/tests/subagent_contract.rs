//! Sub-agent behaviour, against the real store and the shared loop.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use sunday_agent::AutoApprove;
use sunday_extensions::{ModelFactory, SpawnRequest, SubAgentHub};
use sunday_protocol::{
    CoreError, EventKind, HostKind, Model, ModelDelta, ModelRequest, ModelTurn, Permission,
    RunBudget, RunOutcome, SideEffect, Tool, ToolCall, ToolCtx, ToolOutput, ToolSpec,
};
use sunday_store::{ChildStatus, Store};

struct Scripted {
    turns: Mutex<Vec<ModelTurn>>,
}

impl Scripted {
    fn new(turns: Vec<ModelTurn>) -> Self {
        Self {
            turns: Mutex::new(turns),
        }
    }
}

#[async_trait::async_trait]
impl Model for Scripted {
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

struct Factory {
    turns: Vec<ModelTurn>,
    built: Mutex<Vec<String>>,
    fail: bool,
}

impl ModelFactory for Factory {
    fn build(&self, model_id: &str) -> Result<Arc<dyn Model>, CoreError> {
        self.built.lock().unwrap().push(model_id.to_owned());
        if self.fail {
            return Err(CoreError::unsupported(format!("model {model_id}")));
        }
        Ok(Arc::new(Scripted::new(self.turns.clone())))
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

fn turn_calling(id: &str, name: &str) -> ModelTurn {
    ModelTurn {
        text: Some("working".into()),
        reasoning: None,
        tool_calls: vec![ToolCall {
            id: id.into(),
            name: name.into(),
            args: serde_json::json!({}),
        }],
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

fn budget(rounds: u32) -> RunBudget {
    RunBudget {
        max_rounds: rounds,
        max_tool_calls: 8,
        wall_clock: std::time::Duration::from_secs(10),
    }
}

fn spawn_request(parent: &str, tools: Vec<&str>) -> SpawnRequest {
    SpawnRequest {
        parent_thread: parent.into(),
        model_id: "child-model".into(),
        guide: "do the sub task".into(),
        granted_tools: tools.into_iter().map(str::to_owned).collect(),
        budget: budget(3),
    }
}

fn setup(turns: Vec<ModelTurn>) -> (tempfile::TempDir, Arc<Mutex<Store>>, Arc<Factory>) {
    let dir = tempfile::tempdir().unwrap();
    let store = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    let factory = Arc::new(Factory {
        turns,
        built: Mutex::new(Vec::new()),
        fail: false,
    });
    (dir, store, factory)
}

#[tokio::test]
async fn a_child_runs_through_the_shared_loop_and_records_its_own_thread() {
    let (_dir, store, factory) = setup(vec![turn_text("child done")]);
    let hub = SubAgentHub::new(factory.clone(), 2);
    let record = hub
        .spawn(&store, spawn_request("parent", vec!["read_file"]))
        .unwrap();

    let runs = Arc::new(AtomicUsize::new(0));
    let tool = Counting::new("read_file", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];

    let outcome = hub
        .run_child(&store, &tools, &AutoApprove, &record.child_id, budget(3))
        .await
        .unwrap();

    assert_eq!(
        outcome,
        RunOutcome::Completed {
            text: "child done".into()
        }
    );
    assert_eq!(factory.built.lock().unwrap().as_slice(), ["child-model"]);

    // Events land on the child thread, and the run goes through the same loop the
    // parent uses: RunStarted then RunCompleted.
    let store = store.lock().unwrap();
    let events = store.events(&record.child_thread, 0).unwrap();
    assert_eq!(events[0].kind, EventKind::RunStarted);
    assert!(events.iter().any(|e| e.kind == EventKind::RunCompleted));
    assert!(
        store.events("parent", 0).unwrap().is_empty(),
        "the parent thread must not be polluted by a child run"
    );
    let children = store.list_children("parent").unwrap();
    assert_eq!(children.len(), 1);
    assert_eq!(children[0].status, ChildStatus::Completed);
    assert_eq!(children[0].result.as_deref(), Some("child done"));
}

#[tokio::test]
async fn a_child_cannot_use_a_tool_it_was_not_granted() {
    let (_dir, store, factory) = setup(vec![turn_calling("c1", "secret_tool")]);
    let hub = SubAgentHub::new(factory, 2);
    let record = hub
        .spawn(&store, spawn_request("parent", vec!["allowed_tool"]))
        .unwrap();

    let runs = Arc::new(AtomicUsize::new(0));
    let allowed = Counting::new("allowed_tool", runs.clone());
    let secret = Counting::new("secret_tool", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&allowed, &secret];

    let err = hub
        .run_child(&store, &tools, &AutoApprove, &record.child_id, budget(3))
        .await
        .unwrap_err();
    match err {
        CoreError::UnsupportedCapability { capability } => assert_eq!(capability, "secret_tool"),
        other => panic!("expected the tool to be refused, got {other:?}"),
    }
    assert_eq!(runs.load(Ordering::SeqCst), 0);
    assert_eq!(
        store
            .lock()
            .unwrap()
            .get_child(&record.child_id)
            .unwrap()
            .unwrap()
            .status,
        ChildStatus::Failed
    );
}

#[tokio::test]
async fn a_cancelled_child_executes_nothing() {
    let (_dir, store, factory) = setup(vec![turn_calling("c1", "write_file")]);
    let hub = SubAgentHub::new(factory, 2);
    let record = hub
        .spawn(&store, spawn_request("parent", vec!["write_file"]))
        .unwrap();
    assert!(hub.cancel(&store, &record.child_id).unwrap());

    let runs = Arc::new(AtomicUsize::new(0));
    let tool = Counting::new("write_file", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];

    let outcome = hub
        .run_child(&store, &tools, &AutoApprove, &record.child_id, budget(3))
        .await
        .unwrap();
    assert_eq!(outcome, RunOutcome::Cancelled);
    assert_eq!(runs.load(Ordering::SeqCst), 0);
    assert_eq!(
        store
            .lock()
            .unwrap()
            .get_child(&record.child_id)
            .unwrap()
            .unwrap()
            .status,
        ChildStatus::Cancelled
    );
}

#[tokio::test]
async fn the_child_limit_rejects_instead_of_queueing_silently() {
    let (_dir, store, factory) = setup(vec![turn_text("ok")]);
    let hub = SubAgentHub::new(factory, 1);
    hub.spawn(&store, spawn_request("parent", vec!["read_file"]))
        .unwrap();
    let err = hub
        .spawn(&store, spawn_request("parent", vec!["read_file"]))
        .unwrap_err();
    assert!(matches!(err, CoreError::Rejected { .. }), "got {err:?}");
    assert_eq!(hub.running(), 1);
}

#[tokio::test]
async fn a_child_budget_stops_a_runaway_child() {
    let (_dir, store, factory) = setup(vec![
        turn_calling("c1", "ping"),
        turn_calling("c2", "ping"),
        turn_calling("c3", "ping"),
    ]);
    let hub = SubAgentHub::new(factory, 2);
    let record = hub
        .spawn(&store, spawn_request("parent", vec!["ping"]))
        .unwrap();
    let runs = Arc::new(AtomicUsize::new(0));
    let tool = Counting::new("ping", runs.clone());
    let tools: Vec<&dyn Tool> = vec![&tool];

    let outcome = hub
        .run_child(&store, &tools, &AutoApprove, &record.child_id, budget(2))
        .await
        .unwrap();
    assert!(matches!(outcome, RunOutcome::BudgetExhausted { .. }));
    assert_eq!(runs.load(Ordering::SeqCst), 2);
    assert_eq!(
        store
            .lock()
            .unwrap()
            .get_child(&record.child_id)
            .unwrap()
            .unwrap()
            .status,
        ChildStatus::BudgetExhausted
    );
}

#[tokio::test]
async fn a_host_that_cannot_build_the_model_fails_at_spawn() {
    let dir = tempfile::tempdir().unwrap();
    let store = Arc::new(Mutex::new(Store::open(dir.path().join("c.db")).unwrap()));
    let factory = Arc::new(Factory {
        turns: vec![turn_text("x")],
        built: Mutex::new(Vec::new()),
        fail: true,
    });
    let hub = SubAgentHub::new(factory, 2);
    let err = hub
        .spawn(&store, spawn_request("parent", vec!["read_file"]))
        .unwrap_err();
    assert!(matches!(err, CoreError::UnsupportedCapability { .. }));
    assert!(
        store
            .lock()
            .unwrap()
            .list_children("parent")
            .unwrap()
            .is_empty(),
        "a failed spawn must not leave a record"
    );
    assert_eq!(hub.running(), 0, "the slot must be released");
}

#[tokio::test]
async fn a_child_left_running_by_a_crash_is_reported_as_orphaned() {
    let (_dir, store, factory) = setup(vec![turn_text("x")]);
    let hub = SubAgentHub::new(factory, 2);
    let record = hub
        .spawn(&store, spawn_request("parent", vec!["read_file"]))
        .unwrap();
    // No run_child: the process "died" here.

    let plan = store.lock().unwrap().recover().unwrap();
    assert_eq!(plan.orphaned_children, vec![record.child_id.clone()]);
    assert_eq!(
        store
            .lock()
            .unwrap()
            .get_child(&record.child_id)
            .unwrap()
            .unwrap()
            .status,
        ChildStatus::Orphaned
    );
}

#[tokio::test]
async fn a_child_with_no_usable_tools_is_refused_before_running() {
    let (_dir, store, factory) = setup(vec![turn_text("x")]);
    let hub = SubAgentHub::new(factory, 2);
    let record = hub
        .spawn(&store, spawn_request("parent", vec!["ghost_tool"]))
        .unwrap();

    let err = hub
        .run_child(&store, &[], &AutoApprove, &record.child_id, budget(2))
        .await
        .unwrap_err();
    assert!(
        matches!(err, CoreError::PermissionDenied { .. }),
        "got {err:?}"
    );
}

#[tokio::test]
async fn a_spawn_without_any_granted_tool_is_refused() {
    let (_dir, store, factory) = setup(vec![turn_text("x")]);
    let hub = SubAgentHub::new(factory, 2);
    let err = hub
        .spawn(&store, spawn_request("parent", vec![]))
        .unwrap_err();
    assert!(matches!(err, CoreError::InvalidRequest { .. }));
}
