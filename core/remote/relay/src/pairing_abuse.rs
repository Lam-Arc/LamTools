//! Bounded, reconnect-independent limits for the six-digit lookup oracle.

use std::{collections::HashMap, sync::Mutex};

const WINDOW_MS: u64 = 5 * 60 * 1000;
const PRINCIPAL_LIMIT: u32 = 5;
const GLOBAL_LIMIT: u32 = 50;
const MAX_PRINCIPALS: usize = 2048;

#[derive(Default)]
struct Window {
    started_ms: u64,
    count: u32,
}

impl Window {
    fn refresh(&mut self, now: u64) {
        if now.saturating_sub(self.started_ms) >= WINDOW_MS {
            self.started_ms = now;
            self.count = 0;
        }
    }
}

#[derive(Default)]
struct Budgets {
    global: Window,
    principals: HashMap<String, Window>,
}

#[derive(Default)]
pub(crate) struct PairingAbuseGuard(Mutex<Budgets>);

impl PairingAbuseGuard {
    /// Count all lookups, successful or not. Key by account, not rotating node,
    /// access token or attacker-supplied forwarding headers. Fail closed.
    pub(crate) fn admit(&self, principal: &str, now: u64) -> bool {
        let Ok(mut budgets) = self.0.lock() else {
            return false;
        };
        budgets.global.refresh(now);
        budgets
            .principals
            .retain(|_, value| now.saturating_sub(value.started_ms) < WINDOW_MS);
        if budgets.global.count >= GLOBAL_LIMIT || principal.len() > 256 {
            return false;
        }
        if !budgets.principals.contains_key(principal) && budgets.principals.len() >= MAX_PRINCIPALS
        {
            return false;
        }
        let window = budgets
            .principals
            .entry(principal.to_owned())
            .or_insert_with(|| Window {
                started_ms: now,
                count: 0,
            });
        window.refresh(now);
        if window.count >= PRINCIPAL_LIMIT {
            return false;
        }
        window.count += 1;
        budgets.global.count += 1;
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    #[test]
    fn account_budget_survives_node_token_and_connection_changes_and_expires() {
        let guard = PairingAbuseGuard::default();
        for _ in 0..PRINCIPAL_LIMIT {
            assert!(guard.admit("account", 100));
        }
        assert!(!guard.admit("account", 101));
        assert!(guard.admit("other-account", 101));
        assert!(guard.admit("account", 100 + WINDOW_MS));
    }

    #[test]
    fn rotating_accounts_cannot_bypass_global_budget() {
        let guard = PairingAbuseGuard::default();
        for index in 0..GLOBAL_LIMIT {
            assert!(guard.admit(&format!("user-{index}"), 100));
        }
        assert!(!guard.admit("fresh-user", 100));
    }

    #[test]
    fn parallel_requests_reserve_budget_atomically() {
        let guard = Arc::new(PairingAbuseGuard::default());
        let handles: Vec<_> = (0..40)
            .map(|_| {
                let guard = guard.clone();
                std::thread::spawn(move || guard.admit("same-account", 100))
            })
            .collect();
        assert_eq!(
            handles
                .into_iter()
                .filter_map(|handle| handle.join().ok())
                .filter(|allowed| *allowed)
                .count(),
            PRINCIPAL_LIMIT as usize
        );
    }
}
