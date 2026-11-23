//! Sunday device transport.
//!
//! user:“P2P 作为独立、可复用的传输组件，不绑定 Python 或 Rust Agent Core”+
//! (这里只做四件事：身份、配对票据、可信设备、把一帧 JSON 送到对面并拿回一帧)。
//! 会话、工具、审批都是上层的事，这一层不认识它们。
//!
//! 连接优先直连：Iroh 先尝试局域网/公网打洞，打不通再走中继，且中继只转发加密流量。
//! user:“用公共 Relay 仅作回退，允许用户自己配置中继”+(presets::N0 用 n0 的公共
//! relay 和 DNS 发现；以后要做自定义 relay，只改这里构造 endpoint 的参数)。

/// Re-exported so hosts never pin a second iroh version.
pub use iroh;

pub mod events;
pub mod identity;
pub mod gate;
pub mod link;
pub mod pair;
pub mod recovery;
pub mod proxy;
pub mod qr;
pub mod rpc;
pub mod scan;
pub mod state;
pub mod ticket;
pub mod transfer;
pub mod trust;
pub mod watch;

pub use identity::{dialable_addr, relay_summary, Identity, ALPN};
pub use events::{event_seq, initialize_params, pump_core_events, Cursor};
/// 状态通道的事件类型与解析器：宿主与传输进程共用同一份（宿主不能引 iroh，但能引它）。
pub use sunday_p2p_status::{
    parse_line as parse_status_line, StatusError, StatusEvent, PREFIX as STATUS_PREFIX,
};
pub use gate::{Admission, CODE_PAIRING_EXPIRED, CODE_PAIRING_INVALID, CODE_PAIRING_USED, CODE_REVOKED, CODE_UNPAIRED};
pub use link::{Client, Frame, PathKind, ServerLink};
pub use pair::{PairingGrants, PairingTicket};
pub use recovery::{Backoff, Delivery, Outbox, SendStart};
pub use state::{CoreLayer, DeviceLayer, Layers, Reason, SessionLayer, View};
pub use proxy::call_core;
pub use qr::ticket_qr_svg;
pub use scan::{decode_qr_luma, scan_qr_file};
pub use ticket::{decode_any_ticket, decode_ticket, encode_ticket};
pub use trust::{TrustStore, TrustedDevice};
pub use watch::{PendingSend, ReliableSend, WatchOptions};
