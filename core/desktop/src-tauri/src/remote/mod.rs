//! Remote control boundary for the desktop application.
//!
//! Core deliberately remains bound to loopback.  This module is the only
//! place that may accept a mobile connection and proxy bytes to Core.  The
//! first implementation is intentionally self-contained so it can be tested
//! without a relay service; relay and native secure-store adapters implement
//! the same boundaries in their own modules.

pub mod control;
mod diagnostics;
pub mod gateway;
pub mod identity;
pub mod lan;
pub mod pairing;
pub mod relay;
pub mod secure_store;
pub mod tunnel;

pub const REMOTE_PROTOCOL: &str = "lamtools-remote";
pub const REMOTE_PROTOCOL_VERSION: u8 = 1;

pub use control::{start_local_control_server, ControlServer};
pub use gateway::{
    DesktopAccountStatus, GatewayStartOptions, GatewayStatus, NodeIdentityStatus,
    RemoteGatewayManager,
};
pub use pairing::PairingCodePayload;
pub use secure_store::DesktopAccountSession;
