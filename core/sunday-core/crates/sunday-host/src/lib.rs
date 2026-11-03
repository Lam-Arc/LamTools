//! Composition layer.
//!
//! Two things live here and nowhere else: the single-writer guard for a data
//! directory, and the adapter that speaks the existing desktop protocol. Neither
//! belongs in the agent, the store, or a platform host.

pub mod app_server;
pub mod lock;
pub mod policy;
pub mod runner;
pub mod token;
