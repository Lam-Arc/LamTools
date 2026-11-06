//! The device's own key, and the endpoint built from it.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use iroh::{endpoint::presets, Endpoint, SecretKey};

/// user:“共享设备管理、配对、认证和通信协议，避免 Windows 与 Android 分别维护两套实现”+
/// (同一个 ALPN，同一套帧，两端互为客户端与服务端)。
pub const ALPN: &[u8] = b"sunday/p2p/1";

/// A node key plus where it is stored.
///
/// The key is the device identity: it is what the peer authenticates during the QUIC
/// handshake, and what a pairing ticket ultimately points at. Losing it means every
/// other device has to pair again — so it lives in the app's own data directory and is
/// written once, atomically.
pub struct Identity {
    key: SecretKey,
    path: PathBuf,
}

impl Identity {
    /// Loads the key, creating it on first run.
    pub fn load_or_create(dir: &Path) -> Result<Self> {
        let path = dir.join("p2p-identity.key");
        if let Ok(text) = std::fs::read_to_string(&path) {
            let trimmed = text.trim();
            if !trimmed.is_empty() {
                let bytes = hex_decode(trimmed).context("p2p-identity.key is not valid hex")?;
                if bytes.len() != 32 {
                    bail!("p2p-identity.key must be 32 bytes, found {}", bytes.len());
                }
                let mut raw = [0u8; 32];
                raw.copy_from_slice(&bytes);
                let key = SecretKey::from_bytes(&raw);
                return Ok(Self { key, path });
            }
        }
        std::fs::create_dir_all(dir).ok();
        let key = SecretKey::generate();
        let text = hex_encode(&key.to_bytes());
        let temporary = path.with_extension("tmp");
        std::fs::write(&temporary, text).context("cannot write the p2p identity")?;
        std::fs::rename(&temporary, &path).context("cannot install the p2p identity")?;
        Ok(Self { key, path })
    }

    pub fn secret(&self) -> &SecretKey {
        &self.key
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// An endpoint that accepts connections and dials peers.
    ///
    /// One endpoint per process: iroh keeps a single relay connection and a single hole
    /// punched path per peer, and two endpoints in one app would duplicate both.
    pub async fn endpoint(&self) -> Result<Endpoint> {
        Endpoint::builder(presets::N0)
            .alpns(vec![ALPN.to_vec()])
            .secret_key(self.key.clone())
            .bind()
            .await
            .context("cannot bind the p2p endpoint")
    }
}

fn hex_encode(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(DIGITS[(byte >> 4) as usize] as char);
        out.push(DIGITS[(byte & 0x0f) as usize] as char);
    }
    out
}

fn hex_decode(text: &str) -> Result<Vec<u8>> {
    if text.len() % 2 != 0 {
        bail!("odd number of hex digits");
    }
    let mut out = Vec::with_capacity(text.len() / 2);
    let bytes = text.as_bytes();
    for pair in bytes.chunks(2) {
        let high = (pair[0] as char).to_digit(16).context("bad hex digit")? as u8;
        let low = (pair[1] as char).to_digit(16).context("bad hex digit")? as u8;
        out.push((high << 4) | low);
    }
    Ok(out)
}
