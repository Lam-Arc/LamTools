//! Composition layer.
//!
//! Two things live here and nowhere else: the single-writer guard for a data
//! directory, and the adapter that speaks the existing desktop protocol. Neither
//! belongs in the agent, the store, or a platform host.

pub mod app_server;
pub mod lifecycle;
pub mod lock;
pub mod policy;
// Shared with the hosts: a permission rule that each host reimplements is a rule
// that will be right in one place and wrong in the others.
pub mod private_file;
pub mod provider;
pub mod runner;
pub mod token;
