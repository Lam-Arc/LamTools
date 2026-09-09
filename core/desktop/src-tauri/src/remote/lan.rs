use serde::Serialize;
use std::collections::HashMap;

use mdns_sd::{ServiceDaemon, ServiceInfo};

/// mDNS advertisement data.  The native mDNS publisher is kept behind this
/// value object so the gateway does not expose tokens or Core addresses.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LanAdvertisement {
    pub service_type: String,
    pub protocol_version: String,
    pub device_id: String,
    pub port: u16,
}

pub struct LanPublisher {
    daemon: ServiceDaemon,
    fullname: String,
}

impl LanPublisher {
    pub fn start(advertisement: &LanAdvertisement, host: &str) -> Result<Self, String> {
        let daemon = ServiceDaemon::new().map_err(|error| error.to_string())?;
        let mut properties = HashMap::new();
        properties.insert("device_id".to_string(), advertisement.device_id.clone());
        properties.insert(
            "protocol_version".to_string(),
            advertisement.protocol_version.clone(),
        );
        let instance = format!("LamTools-{}", advertisement.device_id);
        let hostname = format!("{}.local.", advertisement.device_id.replace('_', "-"));
        let service = ServiceInfo::new(
            &advertisement.service_type,
            &instance,
            &hostname,
            host,
            advertisement.port,
            Some(properties),
        )
        .map_err(|error| error.to_string())?
        .enable_addr_auto();
        let fullname = service.get_fullname().to_string();
        daemon
            .register(service)
            .map_err(|error| error.to_string())?;
        Ok(Self { daemon, fullname })
    }

    pub fn stop(&self) {
        let _ = self.daemon.unregister(&self.fullname);
        let _ = self.daemon.shutdown();
    }
}

impl Drop for LanPublisher {
    fn drop(&mut self) {
        self.stop();
    }
}

impl LanAdvertisement {
    pub fn new(device_id: impl Into<String>, port: u16) -> Self {
        Self {
            service_type: "_lamtools._tcp.local.".to_string(),
            protocol_version: "1".to_string(),
            device_id: device_id.into(),
            port,
        }
    }
}
