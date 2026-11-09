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

/// 被撤销的设备。
///
/// user:“允许撤销授权”+(首次连接本来是自动信任的，只把设备从名单里删掉，它下一次连上来
/// 又会被当成“第一次见面”重新信任，撤销等于没做。撤销必须留一条记录，而且要在自动信任
/// 之前检查)。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RevokedDevice {
    pub id: String,
    #[serde(default)]
    pub name: String,
    pub revoked_at: u64,
}

#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct TrustStore {
    #[serde(default)]
    pub devices: Vec<TrustedDevice>,
    #[serde(default)]
    pub revoked: Vec<RevokedDevice>,
    #[serde(skip)]
    path: PathBuf,
}

impl TrustStore {
    pub fn load(dir: &Path) -> Result<Self> {
        let path = dir.join("p2p-trust.json");
        if !path.exists() {
            return Ok(Self {
                devices: Vec::new(),
                revoked: Vec::new(),
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

    /// 这台设备被用户撤销过：握手阶段直接拒绝，不再走自动信任。
    pub fn is_revoked(&self, id: &str) -> bool {
        self.revoked.iter().any(|device| device.id == id)
    }

    /// 重新从磁盘读取名单。
    ///
    /// user:“允许撤销授权”+(宿主撤销时改的是 `p2p-trust.json`，传输进程手里是启动时读的
    /// 那份内存副本。不重读就会变成「列表里已经没有它了，它还能连进来」，而且下一次有
    /// 新设备接入时 `save()` 会把撤销记录整条覆盖回去。)
    pub fn reload(&mut self) -> Result<()> {
        if self.path.as_os_str().is_empty() {
            return Ok(());
        }
        if !self.path.exists() {
            // 文件被删掉视为「撤销所有设备」，而不是继续信任内存里的旧名单。
            self.devices.clear();
            return Ok(());
        }
        let text = std::fs::read_to_string(&self.path).context("cannot read p2p-trust.json")?;
        let parsed: Self = serde_json::from_str(&text).context("p2p-trust.json is not valid JSON")?;
        self.devices = parsed.devices;
        self.revoked = parsed.revoked;
        Ok(())
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

    /// user:“允许撤销授权”+(删掉即失效，而且记下这次撤销，下一次握手要拒绝它)。
    pub fn revoke(&mut self, id: &str) -> bool {
        let name = self
            .devices
            .iter()
            .find(|device| device.id == id)
            .map(|device| device.name.clone())
            .unwrap_or_default();
        let before = self.devices.len();
        self.devices.retain(|device| device.id != id);
        let removed = self.devices.len() != before;
        let recorded = if self.revoked.iter().any(|device| device.id == id) {
            false
        } else {
            self.revoked.push(RevokedDevice {
                id: id.to_owned(),
                name,
                revoked_at: now(),
            });
            true
        };
        removed || recorded
    }

    /// 用户重新允许一台被撤销的设备：删掉撤销记录，下一次连接按首次配对处理。
    pub fn allow(&mut self, id: &str) -> bool {
        let before = self.revoked.len();
        self.revoked.retain(|device| device.id != id);
        self.revoked.len() != before
    }
}

fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// user:“撤销设备要真的生效”+(改文件之后，下一次握手必须看不到这台设备)。
    #[test]
    fn reload_picks_up_a_revocation_written_by_the_host() {
        let dir = std::env::temp_dir().join(format!("sunday-trust-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut server_side = TrustStore::load(&dir).unwrap();
        server_side.trust("phone-1", "Phone");
        server_side.save().unwrap();

        // 宿主那一侧：独立读文件、撤销、写回。
        let mut host_side = TrustStore::load(&dir).unwrap();
        assert!(host_side.revoke("phone-1"));
        host_side.save().unwrap();

        // 传输进程不重启，只重读。
        server_side.reload().unwrap();
        assert!(!server_side.is_trusted("phone-1"));
        assert!(server_side.is_revoked("phone-1"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 撤销之后，这台设备不能靠“首次连接自动信任”重新混进来。
    #[test]
    fn a_revoked_device_is_not_trusted_again_by_first_contact() {
        let mut store = TrustStore::default();
        store.trust("phone-2", "Phone");
        store.revoke("phone-2");
        // 重新连接时的路径：先看撤销名单，再谈自动信任。
        assert!(store.is_revoked("phone-2"));
        assert!(!store.is_trusted("phone-2"));
        // 用户明确允许之后才回到可以配对的状态。
        assert!(store.allow("phone-2"));
        assert!(!store.is_revoked("phone-2"));
    }
}
