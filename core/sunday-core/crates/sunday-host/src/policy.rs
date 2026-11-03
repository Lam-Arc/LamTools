//! Who may run which tool, without asking a human.
//!
//! The previous design had one boolean, `auto_approve`, which either asked for
//! everything or approved everything. On Android it defaulted to `true`, so a
//! freshly installed app would silently write and delete files. That is not a
//! tuning problem; a single flag cannot express "reading is fine, writing needs a
//! decision".
//!
//! This replaces it with an explicit grant list:
//!
//!   * `SideEffect::Pure` tools may be auto-approved, because reading changes
//!     nothing. Asking a user to confirm every file read makes the product
//!     unusable and trains them to click approve.
//!   * Anything with a side effect asks, unless the host names that exact tool id
//!     in `granted`.
//!
//! There is deliberately no "grant everything" shortcut. A host that wants a tool
//! auto-approved must list it, which means the decision is visible in that host's
//! configuration.

use std::collections::BTreeSet;
use sunday_agent::{Approval, Approver};
use sunday_protocol::{Permission, SideEffect, ToolCall, ToolSpec};

/// Which tools a host may run without asking a human.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GrantPolicy {
    /// Tool ids explicitly allowed to run without asking. Empty by default.
    pub granted: BTreeSet<String>,
    /// Whether read-only tools are auto-approved. On by default because reading
    /// has no side effect; turn it off for a paranoid host.
    pub auto_pure: bool,
}

impl GrantPolicy {
    /// Read-only tools allowed, nothing with a side effect. This is the default
    /// for every host and the only sane starting point.
    pub fn read_only() -> Self {
        Self {
            granted: BTreeSet::new(),
            auto_pure: true,
        }
    }

    /// Read-only tools allowed, plus the named tools. Used by tests and by a host
    /// that has a genuine reason to pre-authorise a specific action.
    pub fn with_grants<I, S>(ids: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: Into<String>,
    {
        Self {
            granted: ids.into_iter().map(Into::into).collect(),
            auto_pure: true,
        }
    }

    /// Nothing is auto-approved, not even reads.
    pub fn ask_for_everything() -> Self {
        Self {
            granted: BTreeSet::new(),
            auto_pure: false,
        }
    }

    /// The decision for one call. Explicit, and testable without a store.
    pub fn decide(&self, spec: &ToolSpec) -> Approval {
        if spec.permission == Permission::HardBlock {
            return Approval::Deny {
                reason: "this tool never runs".into(),
            };
        }
        if self.granted.contains(&spec.id) {
            return Approval::Auto;
        }
        if self.auto_pure && spec.side_effect == SideEffect::Pure {
            return Approval::Auto;
        }
        Approval::Ask
    }
}

impl Approver for GrantPolicy {
    fn decide(&self, _call: &ToolCall, spec: &ToolSpec) -> Approval {
        GrantPolicy::decide(self, spec)
    }
}

/// A grant policy the host can change while turns are running.
///
/// The agent asks through `Approver` on every tool call, so swapping the policy under
/// it takes effect on the next call rather than at the next launch. Writes are rare
/// and reads are on the hot path, which is what a `RwLock` is for.
#[derive(Debug)]
pub struct LivePolicy {
    inner: std::sync::RwLock<GrantPolicy>,
}

impl LivePolicy {
    pub fn new(policy: GrantPolicy) -> Self {
        Self {
            inner: std::sync::RwLock::new(policy),
        }
    }

    pub fn replace(&self, policy: GrantPolicy) {
        // A poisoned lock would mean a panic while holding it; the policy is a plain
        // value, so recovering the last written one is better than failing every
        // future tool call.
        match self.inner.write() {
            Ok(mut guard) => *guard = policy,
            Err(poisoned) => *poisoned.into_inner() = policy,
        }
    }

    pub fn snapshot(&self) -> GrantPolicy {
        match self.inner.read() {
            Ok(guard) => guard.clone(),
            Err(poisoned) => poisoned.into_inner().clone(),
        }
    }
}

impl Approver for LivePolicy {
    fn decide(&self, _call: &ToolCall, spec: &ToolSpec) -> Approval {
        match self.inner.read() {
            // The inherent method takes only the spec; the call is not consulted.
            Ok(guard) => GrantPolicy::decide(&guard, spec),
            // Failing closed: an unreadable policy must not approve anything.
            Err(_) => Approval::Ask,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn spec(id: &str, side_effect: SideEffect, permission: Permission) -> ToolSpec {
        ToolSpec {
            id: id.into(),
            description: "test tool".into(),
            input_schema: json!({"type": "object"}),
            side_effect,
            hosts: vec![
                sunday_protocol::HostKind::Windows,
                sunday_protocol::HostKind::Android,
                sunday_protocol::HostKind::Server,
            ],
            permission,
        }
    }

    #[test]
    fn the_default_never_auto_approves_a_side_effect() {
        let policy = GrantPolicy::read_only();
        for side_effect in [SideEffect::Idempotent, SideEffect::NonIdempotent] {
            let tool = spec("write_file", side_effect, Permission::AskUser);
            assert_eq!(
                policy.decide(&tool),
                Approval::Ask,
                "{side_effect:?} was auto-approved by the default policy"
            );
        }
    }

    #[test]
    fn the_default_auto_approves_reading() {
        let policy = GrantPolicy::read_only();
        let tool = spec("read_file", SideEffect::Pure, Permission::AutoAllow);
        assert_eq!(policy.decide(&tool), Approval::Auto);
    }

    #[test]
    fn a_named_grant_is_honoured_and_nothing_else() {
        let policy = GrantPolicy::with_grants(["write_file"]);
        assert_eq!(
            policy.decide(&spec(
                "write_file",
                SideEffect::NonIdempotent,
                Permission::AskUser
            )),
            Approval::Auto
        );
        assert_eq!(
            policy.decide(&spec(
                "delete_file",
                SideEffect::NonIdempotent,
                Permission::AskUser
            )),
            Approval::Ask,
            "a grant for one tool leaked to another"
        );
    }

    #[test]
    fn hard_blocked_tools_are_denied_even_when_granted() {
        let policy = GrantPolicy::with_grants(["dangerous"]);
        let decision = policy.decide(&spec(
            "dangerous",
            SideEffect::NonIdempotent,
            Permission::HardBlock,
        ));
        assert!(
            matches!(decision, Approval::Deny { .. }),
            "got {decision:?}"
        );
    }

    #[test]
    fn a_host_can_ask_for_everything() {
        let policy = GrantPolicy::ask_for_everything();
        assert_eq!(
            policy.decide(&spec("read_file", SideEffect::Pure, Permission::AutoAllow)),
            Approval::Ask
        );
    }

    /// There must be no constructor that approves every side effect by default.
    /// This test encodes that as a property rather than a comment.
    #[test]
    fn no_default_construction_approves_a_write() {
        for policy in [
            GrantPolicy::default(),
            GrantPolicy::read_only(),
            GrantPolicy::ask_for_everything(),
        ] {
            let tool = spec("write_file", SideEffect::NonIdempotent, Permission::AskUser);
            assert_ne!(
                policy.decide(&tool),
                Approval::Auto,
                "a default policy auto-approved a write: {policy:?}"
            );
        }
    }
}
