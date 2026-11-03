//! Sub-agent orchestration.
//!
//! Responsibilities, and only these: creation, permission narrowing, resource
//! budget, lifecycle, result collection.
//!
//! What is deliberately absent: the loop. A child runs through
//! `sunday_agent::run_turn` exactly like the parent does. If this crate ever
//! grows its own round loop, the migration has gone wrong.
//!
//! Records live in the store, not in this crate. The only in-memory state is the
//! cancel flag per child, which is runtime state and cannot outlive the process.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use sunday_agent::{run_turn, Approver, Env, TurnInput};
use sunday_protocol::{CoreError, HostKind, Model, Permission, RunBudget, RunOutcome, Tool};
use sunday_store::{ChildRecord, ChildStatus, Store};

/// Children never choose a provider. The host supplies this.
pub trait ModelFactory: Send + Sync {
    fn build(&self, model_id: &str) -> Result<Arc<dyn Model>, CoreError>;
}

pub struct SpawnRequest {
    pub parent_thread: String,
    pub model_id: String,
    pub guide: String,
    /// Explicit allowlist. Anything not named here is invisible to the child.
    pub granted_tools: Vec<String>,
    pub budget: RunBudget,
}

pub struct SubAgentHub {
    factory: Arc<dyn ModelFactory>,
    max_concurrent: usize,
    running: AtomicUsize,
    cancels: Mutex<HashMap<String, Arc<AtomicBool>>>,
    /// Built once per child at spawn time. Building it twice would ask a host
    /// for two clients and two sets of credentials for one sub-agent.
    models: Mutex<HashMap<String, Arc<dyn Model>>>,
}

impl SubAgentHub {
    pub fn new(factory: Arc<dyn ModelFactory>, max_concurrent: usize) -> Self {
        Self {
            factory,
            max_concurrent,
            running: AtomicUsize::new(0),
            cancels: Mutex::new(HashMap::new()),
            models: Mutex::new(HashMap::new()),
        }
    }

    /// Creates the child and records it durably. The model is built here, once,
    /// so a host cannot be asked for two clients for the same child.
    pub fn spawn(
        &self,
        store: &Mutex<Store>,
        request: SpawnRequest,
    ) -> Result<ChildRecord, CoreError> {
        if request.granted_tools.is_empty() {
            return Err(CoreError::invalid(
                "a child must be granted at least one tool, otherwise it can only talk",
            ));
        }
        let taken = self.running.fetch_add(1, Ordering::SeqCst);
        if taken >= self.max_concurrent {
            self.running.fetch_sub(1, Ordering::SeqCst);
            return Err(CoreError::Rejected {
                reason: format!(
                    "child limit of {} reached; the request was not queued silently",
                    self.max_concurrent
                ),
            });
        }
        // Fail before the record exists rather than halfway through a turn, and
        // keep the client so the run does not build a second one.
        let model = match self.factory.build(&request.model_id) {
            Ok(model) => model,
            Err(err) => {
                self.running.fetch_sub(1, Ordering::SeqCst);
                return Err(err);
            }
        };

        let child_id = {
            let store = store.lock().unwrap();
            let existing = store.list_children(&request.parent_thread)?.len();
            format!("{}-child-{existing}", request.parent_thread)
        };
        let record = ChildRecord {
            child_id: child_id.clone(),
            parent_thread: request.parent_thread.clone(),
            child_thread: format!("{child_id}:thread"),
            model_id: request.model_id,
            guide: request.guide,
            granted_tools: request.granted_tools,
            status: ChildStatus::Running,
            result: None,
        };
        {
            let mut store = store.lock().unwrap();
            store.upsert_child(&record)?;
        }
        self.cancels
            .lock()
            .unwrap()
            .insert(child_id.clone(), Arc::new(AtomicBool::new(false)));
        self.models.lock().unwrap().insert(child_id, model);
        Ok(record)
    }

    /// Runs one child turn through the shared loop.
    pub async fn run_child(
        &self,
        store: &Mutex<Store>,
        all_tools: &[&dyn Tool],
        approver: &dyn Approver,
        child_id: &str,
        budget: RunBudget,
    ) -> Result<RunOutcome, CoreError> {
        let record = {
            let store = store.lock().unwrap();
            store
                .get_child(child_id)?
                .ok_or_else(|| CoreError::invalid(format!("unknown child {child_id}")))?
        };

        let model = self
            .models
            .lock()
            .unwrap()
            .get(child_id)
            .cloned()
            .ok_or_else(|| CoreError::invalid(format!("child {child_id} has no model")))?;
        let cancel = self
            .cancels
            .lock()
            .unwrap()
            .get(child_id)
            .cloned()
            .unwrap_or_else(|| Arc::new(AtomicBool::new(false)));

        // Permission narrowing happens here and nowhere else.
        let tools: Vec<&dyn Tool> = all_tools
            .iter()
            .copied()
            .filter(|tool| {
                record.granted_tools.iter().any(|g| g == &tool.spec().id)
                    && tool.spec().permission != Permission::HardBlock
            })
            .collect();
        if tools.is_empty() {
            return Err(CoreError::PermissionDenied {
                resource: format!(
                    "none of the granted tools exist or are allowed: {:?}",
                    record.granted_tools
                ),
            });
        }

        let env = Env {
            store,
            model: model.as_ref(),
            tools: &tools,
            approver,
            cancel: &cancel,
            workspace: "sub-agents".to_owned(),
            host: HostKind::Server,
            context: None,
        };
        let input = TurnInput {
            thread_id: record.child_thread.clone(),
            turn_id: format!("{child_id}:turn"),
            model_id: record.model_id.clone(),
            system: Some(
                "You are a sub-agent. Do the assigned step, then stop. \
                 Only the tools you were granted are available."
                    .into(),
            ),
            prompt: record.guide.clone(),
        };

        let outcome = run_turn(&env, input, budget).await;
        let (status, text) = match &outcome {
            Ok(RunOutcome::Completed { text }) => (ChildStatus::Completed, Some(text.clone())),
            Ok(RunOutcome::Cancelled) => (ChildStatus::Cancelled, None),
            Ok(RunOutcome::NeedsApproval { .. }) => (ChildStatus::WaitingApproval, None),
            Ok(RunOutcome::BudgetExhausted { .. }) => (ChildStatus::BudgetExhausted, None),
            Ok(RunOutcome::WaitingForReconciliation { .. }) => {
                (ChildStatus::WaitingReconciliation, None)
            }
            Err(err) => (ChildStatus::Failed, Some(format!("{err}"))),
        };
        {
            let mut store = store.lock().unwrap();
            store.set_child_status(child_id, status, text.as_deref())?;
        }
        self.running.fetch_sub(1, Ordering::SeqCst);
        outcome
    }

    /// Cancels a child that is running or about to run. Cancelling a finished
    /// child is not an error; it simply has nothing to cancel.
    pub fn cancel(&self, store: &Mutex<Store>, child_id: &str) -> Result<bool, CoreError> {
        let flag = self.cancels.lock().unwrap().get(child_id).cloned();
        match flag {
            Some(flag) => {
                flag.store(true, Ordering::SeqCst);
                Ok(true)
            }
            None => {
                let mut store = store.lock().unwrap();
                store.set_child_status(child_id, ChildStatus::Cancelled, None)?;
                Ok(false)
            }
        }
    }

    pub fn running(&self) -> usize {
        self.running.load(Ordering::SeqCst)
    }
}
