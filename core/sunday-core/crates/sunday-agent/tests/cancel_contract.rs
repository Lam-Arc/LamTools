//! Cancellation contract.
//!
//! Cancelling must actually stop work, not merely set a flag the loop notices
//! later. Three things are checked, because they fail independently:
//!
//!   1. a slow model stream stops being read, and the local socket is released
//!   2. after cancel no new tool call is dispatched (invariant I8)
//!   3. a cancelled turn leaves a state a restart can recover from
//!
//! What is *not* claimed anywhere: that the provider stops billing. Cancelling
//! stops this client reading the stream. A provider may keep generating, and
//! saying otherwise would be a lie in the product.

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use sunday_agent::{Approver, AutoApprove, Env, TurnInput};
use sunday_protocol::{
    CancelToken, CoreError, HostKind, Model, ModelDelta, ModelRequest, ModelTurn, RunBudget,
    RunOutcome, Tool, ToolCall, ToolCtx, ToolOutput, ToolSpec, Usage,
};
use sunday_store::Store;

// ---------------------------------------------------------------- fixtures

/// Emits a delta every `tick` forever, or until its own counter says enough.
/// This is the "slow stream" a user presses Stop on.
struct SlowModel {
    tick: Duration,
    /// Deltas this model managed to emit before the loop stopped asking.
    emitted: Arc<AtomicUsize>,
    /// Flips when the caller dropped the request, so the test can prove the
    /// stream was actually abandoned rather than quietly drained.
    dropped: Arc<AtomicBool>,
    /// When set, the model also returns a tool call at the end.
    tool_call_after: Option<ToolCall>,
}

impl SlowModel {
    fn new(tick: Duration) -> Self {
        Self {
            tick,
            emitted: Arc::new(AtomicUsize::new(0)),
            dropped: Arc::new(AtomicBool::new(false)),
            tool_call_after: None,
        }
    }
}

#[async_trait::async_trait]
impl Model for SlowModel {
    async fn stream(
        &self,
        request: ModelRequest,
        sink: &mut (dyn FnMut(ModelDelta) + Send),
    ) -> Result<ModelTurn, CoreError> {
        let mut text = String::new();
        for step in 0..10_000 {
            if request.cancel.is_cancelled() {
                self.dropped.store(true, Ordering::SeqCst);
                return Err(CoreError::Rejected {
                    reason: "cancelled while streaming".into(),
                });
            }
            tokio::time::sleep(self.tick).await;
            self.emitted.fetch_add(1, Ordering::SeqCst);
            let chunk = format!("chunk{step} ");
            text.push_str(&chunk);
            sink(ModelDelta::Text(chunk));
        }
        Ok(ModelTurn {
            text: Some(text),
            reasoning: None,
            tool_calls: self
                .tool_call_after
                .clone()
                .into_iter()
                .collect::<Vec<ToolCall>>(),
            usage: Some(Usage {
                input_tokens: 1,
                output_tokens: 1,
            }),
            provider_state: None,
        })
    }
}

fn temp_store() -> (tempfile::TempDir, Mutex<Store>) {
    let dir = tempfile::tempdir().expect("tempdir");
    let store = Store::open(dir.path().join("core.db")).expect("open");
    (dir, Mutex::new(store))
}

fn input(thread: &str) -> TurnInput {
    TurnInput {
        thread_id: thread.to_owned(),
        turn_id: "turn-1".into(),
        model_id: "slow".into(),
        system: None,
        prompt: "do something long".into(),
    }
}

// ---------------------------------------------------------------- tests

/// A stop during a slow stream must take effect quickly. Each delta takes 20ms,
/// so finishing the whole stream would take 200s; a cancel should land within a
/// few deltas.
#[tokio::test]
async fn stopping_a_slow_stream_stops_reading_it() {
    let (_dir, store) = temp_store();
    let model = SlowModel::new(Duration::from_millis(20));
    let emitted = model.emitted.clone();
    let dropped = model.dropped.clone();
    let cancel = CancelToken::new();
    let auto = AutoApprove;
    let tools: Vec<&dyn Tool> = Vec::new();

    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &auto as &dyn Approver,
        cancel: &cancel,
        workspace: "local".into(),
        host: HostKind::Server,
        context: None,
    };

    // Press Stop after the stream has demonstrably started.
    let stopper = {
        let cancel = cancel.clone();
        let emitted = emitted.clone();
        tokio::spawn(async move {
            while emitted.load(Ordering::SeqCst) < 3 {
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
            let pressed = Instant::now();
            cancel.cancel();
            pressed
        })
    };

    let started = Instant::now();
    let outcome = sunday_agent::run_turn(&env, input("t1"), RunBudget::default())
        .await
        .expect("a cancel is not an error");
    let elapsed = started.elapsed();
    let pressed_at = stopper.await.expect("stopper");

    assert!(
        matches!(outcome, RunOutcome::Cancelled),
        "a cancelled turn must report Cancelled, got {outcome:?}"
    );
    assert!(
        dropped.load(Ordering::SeqCst),
        "the model never observed the cancel, so the stream was not really abandoned"
    );
    let after_press = started
        .elapsed()
        .saturating_sub(pressed_at.duration_since(started));
    assert!(
        after_press < Duration::from_millis(500),
        "the cancel took {after_press:?} to take effect"
    );
    println!(
        "cancel took effect after {:?}; {} of 10000 deltas were emitted; whole run {:?}",
        after_press,
        emitted.load(Ordering::SeqCst),
        elapsed
    );

    // And the journal records why the turn stopped.
    let events = store.lock().unwrap().events("t1", 0).expect("events");
    assert!(
        events
            .iter()
            .any(|e| e.kind == sunday_protocol::EventKind::RunCancelled),
        "no run_cancelled event was written: {:?}",
        events.iter().map(|e| e.kind).collect::<Vec<_>>()
    );
}

/// I8: after cancel, no new tool call starts.
///
/// The realistic shape: the user presses Stop *while a tool is running*. The
/// tool therefore owns the cancel, rather than a separate task racing it. A
/// separate task cannot work here because there is no await point between the
/// tool finishing and the loop checking the flag, so the stopper never gets
/// scheduled, and the test would be measuring the scheduler rather than I8.
#[tokio::test]
async fn no_tool_starts_after_a_cancel() {
    let (_dir, store) = temp_store();
    let runs = Arc::new(AtomicUsize::new(0));
    let cancel = CancelToken::new();

    /// Cancels the turn the first time it runs, like a user hitting Stop during
    /// a slow write.
    struct CancellingTool {
        spec: ToolSpec,
        runs: Arc<AtomicUsize>,
        cancel: CancelToken,
    }

    #[async_trait::async_trait]
    impl Tool for CancellingTool {
        fn spec(&self) -> &ToolSpec {
            &self.spec
        }
        async fn execute(
            &self,
            _args: serde_json::Value,
            _ctx: &ToolCtx,
        ) -> Result<ToolOutput, CoreError> {
            self.runs.fetch_add(1, Ordering::SeqCst);
            // Press Stop in the middle of the work.
            self.cancel.cancel();
            tokio::time::sleep(Duration::from_millis(5)).await;
            Ok(ToolOutput {
                content: "ran".into(),
                is_error: false,
            })
        }
    }

    let tool = CancellingTool {
        spec: ToolSpec {
            id: "counted".into(),
            description: "cancels the turn while it runs".into(),
            input_schema: serde_json::json!({"type": "object", "properties": {}}),
            side_effect: sunday_protocol::SideEffect::Pure,
            hosts: vec![HostKind::Windows, HostKind::Android, HostKind::Server],
            permission: sunday_protocol::Permission::AutoAllow,
        },
        runs: runs.clone(),
        cancel: cancel.clone(),
    };

    struct TwoCalls;
    #[async_trait::async_trait]
    impl Model for TwoCalls {
        async fn stream(
            &self,
            _request: ModelRequest,
            _sink: &mut (dyn FnMut(ModelDelta) + Send),
        ) -> Result<ModelTurn, CoreError> {
            Ok(ModelTurn {
                text: None,
                reasoning: None,
                tool_calls: vec![
                    ToolCall {
                        id: "call-1".into(),
                        name: "counted".into(),
                        args: serde_json::json!({}),
                    },
                    ToolCall {
                        id: "call-2".into(),
                        name: "counted".into(),
                        args: serde_json::json!({}),
                    },
                ],
                usage: None,
                provider_state: None,
            })
        }
    }

    let tools: Vec<&dyn Tool> = vec![&tool];
    let auto = AutoApprove;
    let model = TwoCalls;
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &auto as &dyn Approver,
        cancel: &cancel,
        workspace: "local".into(),
        host: HostKind::Server,
        context: None,
    };

    let outcome = sunday_agent::run_turn(&env, input("t2"), RunBudget::default())
        .await
        .expect("run");

    assert_eq!(
        runs.load(Ordering::SeqCst),
        1,
        "the second tool call ran after the cancel, which breaks invariant I8"
    );
    assert!(
        matches!(outcome, RunOutcome::Cancelled),
        "expected Cancelled, got {outcome:?}"
    );
}

/// A cancel before the turn begins must not call the model at all.
#[tokio::test]
async fn a_cancel_before_the_first_round_never_calls_the_model() {
    let (_dir, store) = temp_store();
    let model = SlowModel::new(Duration::from_millis(20));
    let emitted = model.emitted.clone();
    let cancel = CancelToken::new();
    cancel.cancel();
    let auto = AutoApprove;
    let tools: Vec<&dyn Tool> = Vec::new();

    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &auto as &dyn Approver,
        cancel: &cancel,
        workspace: "local".into(),
        host: HostKind::Server,
        context: None,
    };
    let outcome = sunday_agent::run_turn(&env, input("t3"), RunBudget::default())
        .await
        .expect("run");
    assert!(matches!(outcome, RunOutcome::Cancelled));
    assert_eq!(
        emitted.load(Ordering::SeqCst),
        0,
        "the model was called despite being cancelled before the turn started"
    );
}

/// A cancelled turn must leave a state a restart can open, read and continue.
#[tokio::test]
async fn a_cancelled_turn_survives_a_restart() {
    let dir = tempfile::tempdir().expect("tempdir");
    let db = dir.path().join("core.db");
    let model = SlowModel::new(Duration::from_millis(5));
    let emitted = model.emitted.clone();
    let cancel = CancelToken::new();

    {
        let store = Mutex::new(Store::open(&db).expect("open"));
        let auto = AutoApprove;
        let tools: Vec<&dyn Tool> = Vec::new();
        let env = Env {
            store: &store,
            model: &model,
            tools: &tools,
            approver: &auto as &dyn Approver,
            cancel: &cancel,
            workspace: "local".into(),
            host: HostKind::Server,
            context: None,
        };
        let stopper = {
            let cancel = cancel.clone();
            let emitted = emitted.clone();
            tokio::spawn(async move {
                while emitted.load(Ordering::SeqCst) < 2 {
                    tokio::time::sleep(Duration::from_millis(2)).await;
                }
                cancel.cancel();
            })
        };
        let outcome = sunday_agent::run_turn(&env, input("t4"), RunBudget::default())
            .await
            .expect("run");
        assert!(matches!(outcome, RunOutcome::Cancelled));
        stopper.await.expect("stopper");
    }

    // Reopen as a restarted process would.
    let mut store = Store::open(&db).expect("reopen");
    let events = store.events("t4", 0).expect("events");
    assert!(
        events
            .iter()
            .any(|e| e.kind == sunday_protocol::EventKind::RunCancelled),
        "the cancellation was not durable: {:?}",
        events.iter().map(|e| e.kind).collect::<Vec<_>>()
    );
    // A cancelled turn must not leave a continuation that would resume it.
    assert!(
        store
            .load_continuation("t4")
            .expect("continuation")
            .is_none(),
        "a cancelled turn left a resumable continuation behind"
    );
    // And recovery must not treat it as an interrupted side effect needing a human.
    let plan = store.recover().expect("recovery");
    assert!(
        plan.unknown.is_empty(),
        "a cancelled turn was reported as an unknown outcome: {:?}",
        plan.unknown
    );
}

/// After a cancel, the same token must be reusable: the next turn is not born
/// cancelled. This is the mistake a shared flag invites.
#[tokio::test]
async fn the_next_turn_is_not_born_cancelled() {
    let (_dir, store) = temp_store();
    let cancel = CancelToken::new();
    cancel.cancel();
    assert!(cancel.is_cancelled());
    cancel.reset();
    assert!(
        !cancel.is_cancelled(),
        "the token stayed cancelled, so the next turn would stop immediately"
    );

    // And a token reset to clean actually lets a turn run.
    struct OneShot(AtomicBool);
    #[async_trait::async_trait]
    impl Model for OneShot {
        async fn stream(
            &self,
            request: ModelRequest,
            _sink: &mut (dyn FnMut(ModelDelta) + Send),
        ) -> Result<ModelTurn, CoreError> {
            assert!(!request.cancel.is_cancelled());
            self.0.store(true, Ordering::SeqCst);
            Ok(ModelTurn {
                text: Some("done".into()),
                reasoning: None,
                tool_calls: Vec::new(),
                usage: None,
                provider_state: None,
            })
        }
    }

    let model = OneShot(AtomicBool::new(false));
    let auto = AutoApprove;
    let tools: Vec<&dyn Tool> = Vec::new();
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &auto as &dyn Approver,
        cancel: &cancel,
        workspace: "local".into(),
        host: HostKind::Server,
        context: None,
    };
    let outcome = sunday_agent::run_turn(&env, input("t5"), RunBudget::default())
        .await
        .expect("run");
    assert!(
        matches!(outcome, RunOutcome::Completed { .. }),
        "{outcome:?}"
    );
    assert!(model.0.load(Ordering::SeqCst), "the model was never called");
}

/// Two threads must cancel independently: stopping one conversation cannot stop
/// another.
#[tokio::test]
async fn cancelling_one_thread_does_not_cancel_another() {
    let a = CancelToken::new();
    let b = CancelToken::new();
    a.cancel();
    assert!(a.is_cancelled());
    assert!(
        !b.is_cancelled(),
        "cancelling one thread cancelled an unrelated one"
    );
    // Clones share the signal; distinct tokens do not.
    let a_clone = a.clone();
    assert!(a_clone.is_cancelled());
    assert_eq!(a, a_clone);
    assert_ne!(a, b);
}

/// The token must be visible to the model layer, which is what makes an HTTP
/// stream abortable. This is a compile-and-behaviour check, not a mock.
#[tokio::test]
async fn the_model_receives_the_same_token_the_loop_holds() {
    struct Inspect(Arc<Mutex<Option<CancelToken>>>);
    #[async_trait::async_trait]
    impl Model for Inspect {
        async fn stream(
            &self,
            request: ModelRequest,
            _sink: &mut (dyn FnMut(ModelDelta) + Send),
        ) -> Result<ModelTurn, CoreError> {
            *self.0.lock().unwrap() = Some(request.cancel.clone());
            Ok(ModelTurn {
                text: Some("ok".into()),
                reasoning: None,
                tool_calls: Vec::new(),
                usage: None,
                provider_state: None,
            })
        }
    }

    let (_dir, store) = temp_store();
    let seen = Arc::new(Mutex::new(None));
    let model = Inspect(seen.clone());
    let cancel = CancelToken::new();
    let auto = AutoApprove;
    let tools: Vec<&dyn Tool> = Vec::new();
    let env = Env {
        store: &store,
        model: &model,
        tools: &tools,
        approver: &auto as &dyn Approver,
        cancel: &cancel,
        workspace: "local".into(),
        host: HostKind::Server,
        context: None,
    };
    let _ = sunday_agent::run_turn(&env, input("t6"), RunBudget::default()).await;

    let received = seen
        .lock()
        .unwrap()
        .clone()
        .expect("the model saw no token");
    assert_eq!(
        received, cancel,
        "the model got a different token, so a stop would never reach it"
    );
    // Cancelling through the loop's handle is observed by the model's clone.
    cancel.cancel();
    assert!(received.is_cancelled());
}
