use std::{
    collections::HashMap,
    future::Future,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};

use tokio::sync::oneshot;

const MAX_LATCHED_CANCELLATIONS: usize = 256;
const LATCH_TTL: Duration = Duration::from_secs(60);

/// A small per-turn cancellation registry shared by the Tauri commands.
///
/// Registration and cancellation take the same mutex, so a cancel request
/// either observes the active turn and wakes it, or leaves a cancelled latch
/// for a command that has not registered yet.  Entries are keyed by turn id,
/// rather than session id, so a later turn in the same session is independent.
#[derive(Clone, Default)]
pub(crate) struct TurnCancellationRegistry {
    entries: Arc<Mutex<HashMap<String, Entry>>>,
}

struct Entry {
    cancelled: Arc<AtomicBool>,
    signal: Option<oneshot::Sender<()>>,
    created_at: Instant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RegisterError {
    AlreadyCancelled,
    AlreadyRunning,
}

impl std::fmt::Display for RegisterError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::AlreadyCancelled => formatter.write_str("turn cancelled"),
            Self::AlreadyRunning => formatter.write_str("turn already running"),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct TurnCancelled;

pub(crate) struct TurnCancellation {
    registry: TurnCancellationRegistry,
    turn_id: String,
    cancelled: Arc<AtomicBool>,
    signal: oneshot::Receiver<()>,
}

impl TurnCancellationRegistry {
    pub(crate) fn register(&self, turn_id: &str) -> Result<TurnCancellation, RegisterError> {
        let mut entries = self
            .entries
            .lock()
            .expect("turn cancellation registry poisoned");
        prune_latches(&mut entries);
        if let Some(entry) = entries.get(turn_id) {
            if entry.cancelled.load(Ordering::Acquire) {
                entries.remove(turn_id);
                return Err(RegisterError::AlreadyCancelled);
            }
            return Err(RegisterError::AlreadyRunning);
        }

        let cancelled = Arc::new(AtomicBool::new(false));
        let (signal, receiver) = oneshot::channel();
        entries.insert(
            turn_id.to_owned(),
            Entry {
                cancelled: cancelled.clone(),
                signal: Some(signal),
                created_at: Instant::now(),
            },
        );
        Ok(TurnCancellation {
            registry: self.clone(),
            turn_id: turn_id.to_owned(),
            cancelled,
            signal: receiver,
        })
    }

    /// Latch cancellation even when the turn command has not registered yet.
    /// Returns true for both an active turn and a newly-created latch.
    pub(crate) fn cancel(&self, turn_id: &str) -> bool {
        let mut entries = self
            .entries
            .lock()
            .expect("turn cancellation registry poisoned");
        prune_latches(&mut entries);
        let entry = entries.entry(turn_id.to_owned()).or_insert_with(|| Entry {
            cancelled: Arc::new(AtomicBool::new(false)),
            signal: None,
            created_at: Instant::now(),
        });
        entry.cancelled.store(true, Ordering::Release);
        if let Some(signal) = entry.signal.take() {
            let _ = signal.send(());
        }
        prune_latches(&mut entries);
        true
    }

    fn finish(&self, turn_id: &str, cancelled: &Arc<AtomicBool>) {
        let Ok(mut entries) = self.entries.lock() else {
            return;
        };
        let remove = entries
            .get(turn_id)
            .map(|entry| Arc::ptr_eq(&entry.cancelled, cancelled))
            .unwrap_or(false);
        if remove {
            entries.remove(turn_id);
        }
    }
}

fn prune_latches(entries: &mut HashMap<String, Entry>) {
    let now = Instant::now();
    entries.retain(|_, entry| {
        entry.signal.is_some() || now.duration_since(entry.created_at) <= LATCH_TTL
    });
    let mut latched = entries
        .iter()
        .filter(|(_, entry)| entry.signal.is_none())
        .map(|(turn_id, entry)| (turn_id.clone(), entry.created_at))
        .collect::<Vec<_>>();
    latched.sort_by_key(|(_, created_at)| *created_at);
    for (turn_id, _) in latched
        .into_iter()
        .take(entries.len().saturating_sub(MAX_LATCHED_CANCELLATIONS))
    {
        entries.remove(&turn_id);
    }
}

impl TurnCancellation {
    /// Race the native turn against its cancellation signal.
    ///
    /// Once cancellation wins, dropping `future` also drops the provider
    /// request or retry sleep owned by that future.
    pub(crate) async fn run<F, T>(mut self, future: F) -> Result<T, TurnCancelled>
    where
        F: Future<Output = T>,
    {
        let result = if self.cancelled.load(Ordering::Acquire) {
            Err(TurnCancelled)
        } else {
            tokio::select! {
                _ = &mut self.signal => Err(TurnCancelled),
                output = future => {
                    if self.cancelled.load(Ordering::Acquire) {
                        Err(TurnCancelled)
                    } else {
                        Ok(output)
                    }
                }
            }
        };
        self.registry.finish(&self.turn_id, &self.cancelled);
        result
    }
}

impl Drop for TurnCancellation {
    fn drop(&mut self) {
        self.registry.finish(&self.turn_id, &self.cancelled);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn cancel_before_registration_is_latched() {
        let registry = TurnCancellationRegistry::default();
        assert!(registry.cancel("turn-before-register"));
        assert!(matches!(
            registry.register("turn-before-register"),
            Err(RegisterError::AlreadyCancelled)
        ));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn cancel_while_future_is_pending_stops_promptly() {
        let registry = TurnCancellationRegistry::default();
        let cancellation = registry.register("turn-pending").unwrap();
        let pending = tokio::spawn(cancellation.run(async {
            tokio::time::sleep(Duration::from_secs(30)).await;
            42
        }));
        tokio::task::yield_now().await;
        assert!(registry.cancel("turn-pending"));
        let result = tokio::time::timeout(Duration::from_secs(1), pending)
            .await
            .expect("cancellation should wake the pending future")
            .expect("cancellation task should not panic");
        assert_eq!(result, Err(TurnCancelled));
    }

    #[tokio::test(flavor = "current_thread")]
    async fn a_new_turn_in_the_same_session_is_independent() {
        let registry = TurnCancellationRegistry::default();
        assert!(registry.cancel("old-turn"));
        let cancellation = registry.register("new-turn").unwrap();
        assert_eq!(
            cancellation.run(async { "new result" }).await,
            Ok("new result")
        );
    }

    #[test]
    fn unmatched_cancel_latches_are_bounded() {
        let registry = TurnCancellationRegistry::default();
        for index in 0..(MAX_LATCHED_CANCELLATIONS + 32) {
            registry.cancel(&format!("unknown-{index}"));
        }
        let entries = registry.entries.lock().unwrap();
        assert!(entries.len() <= MAX_LATCHED_CANCELLATIONS);
        assert!(entries.values().all(|entry| entry.signal.is_none()));
    }
}
