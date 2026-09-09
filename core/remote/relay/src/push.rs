use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PushEventType {
    Approval,
    Question,
}

#[derive(Clone, Debug, Deserialize)]
pub struct PushSignal {
    pub device_id: String,
    pub event_type: PushEventType,
    pub opaque_event_id: String,
}

pub trait PushProvider: Send + Sync {
    fn enabled(&self) -> bool;
    fn send(&self, signal: &PushSignal) -> Result<(), String>;
}

/// The relay starts safely without APNs/FCM credentials. Deployments can
/// replace this provider without changing the payload boundary; conversation
/// content is not represented by `PushSignal` and therefore cannot leak into
/// a platform notification.
pub struct DisabledPushProvider;

impl PushProvider for DisabledPushProvider {
    fn enabled(&self) -> bool {
        false
    }
    fn send(&self, _signal: &PushSignal) -> Result<(), String> {
        Err("push provider is not configured".to_string())
    }
}
