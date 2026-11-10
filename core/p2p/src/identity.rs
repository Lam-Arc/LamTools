//! The device's own key, and the endpoint built from it.

use std::path::{Path, PathBuf};

use anyhow::{bail, Context, Result};
use iroh::endpoint::{presets, IdleTimeout, QuicTransportConfig};
use iroh::{Endpoint, SecretKey};

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
        let relays = extra_relays();
        let mut builder = Endpoint::builder(presets::N0);
        if !relays.is_empty() {
            // user:“允许用户配置自己的中继服务”+(配了就只用配置的 relay，不再依赖公共节点；
            // 不配则用 presets::N0 自带的公共 relay，公共的只做回退)。
            let urls: Vec<iroh::RelayUrl> = relays.iter().filter_map(|url| url.parse().ok()).collect();
            if !urls.is_empty() {
                println!("[sunday-p2p] using {} custom relay(s)", urls.len());
                builder = builder.relay_mode(iroh::RelayMode::custom(urls));
            }
        }
        // user:“手机端远控电脑连接不稳定，频繁断连”+(iroh 默认 30 秒空闲就关连接。手机端
        // 一条大回复正把写方向占住时，应用层心跳排在锁后面发不出去，28 秒后 QUIC 自己把
        // 连接关掉，电脑侧日志就是 cannot write a frame: timed out。这里把空闲上限抬到
        // 120 秒，并让 QUIC 自己每 10 秒保活一次：业务层的锁再忙，链路层也有真实流量)。
        let transport = QuicTransportConfig::builder()
            .keep_alive_interval(std::time::Duration::from_secs(10))
            .max_idle_timeout(Some(
                IdleTimeout::try_from(std::time::Duration::from_secs(120))
                    .context("idle timeout is out of range")?,
            ))
            .build();
        builder
            .transport_config(transport)
            .alpns(vec![ALPN.to_vec()])
            .secret_key(self.key.clone())
            .bind()
            .await
            .context("cannot bind the p2p endpoint")
    }
}

/// Waits briefly for a relay connection, then returns the address a ticket should carry.
///
/// user:“第一次连上了，后面就没有再连上过”+(票据在 endpoint 刚 bind 时就生成，那时还没连上
/// 中继，二维码里只有当时的局域网地址；电脑重启或换网后这个地址就失效，只能一直超时。
/// 出票前先给中继一点时间，让票据带上可复用的中继入口。)
pub async fn dialable_addr(
    endpoint: &Endpoint,
    wait: std::time::Duration,
) -> iroh::EndpointAddr {
    let _ = tokio::time::timeout(wait, endpoint.online()).await;
    endpoint.addr()
}

/// One line per home relay for diagnostics: connected, or the last error.
pub fn relay_summary(endpoint: &Endpoint) -> Vec<String> {
    use iroh::Watcher;
    let mut out = Vec::new();
    for status in endpoint.home_relay_status().get() {
        if status.is_connected() {
            out.push(format!("{} connected", status.url()));
        } else if let Some(error) = status.last_error() {
            out.push(format!("{} error: {error:#}", status.url()));
        } else {
            out.push(format!("{} connecting", status.url()));
        }
    }
    if out.is_empty() {
        out.push("none configured".to_owned());
    }
    out
}

/// Relays the user added through the environment.
///
/// `SUNDAY_P2P_RELAY` and `SUNDAY_P2P_RELAYS` accept one or more URLs separated by commas.
/// A self-hosted relay is often the difference between "works at home" and "works anywhere",
/// and it needs no account: the relay only forwards encrypted traffic addressed by node id.
fn extra_relays() -> Vec<String> {
    let mut found = Vec::new();
    for key in ["SUNDAY_P2P_RELAY", "SUNDAY_P2P_RELAYS"] {
        if let Ok(value) = std::env::var(key) {
            for part in value.split(',') {
                let trimmed = part.trim();
                if !trimmed.is_empty() {
                    found.push(trimmed.to_owned());
                }
            }
        }
    }
    found
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
