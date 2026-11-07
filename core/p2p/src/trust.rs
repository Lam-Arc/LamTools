//! Which peers are allowed in.
//!
//! user:“建立可信设备关系，保存配对状态，允许撤销授权”+(只有在这份名单里的设备才被接受；
//! 撤销就是把 id 删掉，下一次连接在握手阶段就被拒绝，不需要重启)。
//!
//! 传输层本身已经用 TLS 证明了对面的身份（节点公钥），所以名单就是信任的全部内容：
//! 不需要再发一次密码，也没有可以重放的令牌。

use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrustedDevice {
    /// The peer's endpoint id, as iroh prints it.
    pub id: String,
    /// The name the user saw when pairing.
    pub name: String,
    pub added_at: u64,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct TrustStore {
    #[serde(default)]
    pub devices: Vec<TrustedDevice>,
    #[serde(skip)]
    path: PathBuf,
}

impl TrustStore {
    pub fn load(dir: &Path) -> Result<Self> {
        let path = dir.join("p2p-trust.json");
        if !path.exists() {
            return Ok(Self {
                devices: Vec::new(),
                path,
            });
        }
        let text = std::fs::read_to_string(&path).context("cannot read p2p-trust.json")?;
        let mut store: Self =
            serde_json::from_str(&text).context("p2p-trust.json is not valid JSON")?;
        store.path = path;
        Ok(store)
    }

    pub fn save(&self) -> Result<()> {
        if self.path.as_os_str().is_empty() {
            return Ok(());
        }
        let text = serde_json::to_string_pretty(self).context("cannot encode the trust store")?;
        let temporary = self.path.with_extension("tmp");
        std::fs::write(&temporary, text).context("cannot write the trust store")?;
        std::fs::rename(&temporary, &self.path).context("cannot install the trust store")?;
        Ok(())
    }

    pub fn is_trusted(&self, id: &str) -> bool {
        self.devices.iter().any(|device| device.id == id)
    }

    /// Adds a device, replacing an entry with the same id.
    pub fn trust(&mut self, id: &str, name: &str) -> TrustedDevice {
        let device = TrustedDevice {
            id: id.to_owned(),
            name: name.to_owned(),
            added_at: now(),
        };
        self.devices.retain(|item| item.id != id);
        self.devices.push(device.clone());
        device
    }

    /// user:“允许撤销授权”+(删掉即失效，下一次握手就拒绝)。
    pub fn revoke(&mut self, id: &str) -> bool {
        let before = self.devices.len();
        self.devices.retain(|device| device.id != id);
        self.devices.len() != before
    }
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0)
}
