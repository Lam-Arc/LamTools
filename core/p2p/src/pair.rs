//! 配对授权：短时、一次性、绑定节点身份的票据。
//!
//! user:“二维码是短时、一次性的配对授权：有效期明确（建议 ≤5 分钟）、用过即失效、
//! 过期后必须重新生成；重复使用要被拒绝并给出可读原因”+(以前 `sunday1:` 票据只是
//! 「节点 id + 地址」的另一种写法：谁看到这张码，谁就能在任何时候连进来，用完也不作废。
//! 现在出票方用自己的节点私钥签名，票据里带过期时间与一次性随机数，服务端核对签名后
//! 把随机数记成已用，同一张码不能再用第二次)。
//!
//! user:“票据不可伪造（绑定节点身份/公钥）、不可重放到其它设备”+(签名用的是节点私钥，
//! 校验用的是票据里那个节点 id 的公钥：改一个字节就验不过；随机数只能用一次，所以第二台
//! 设备拿同一张码来连会被拒绝)。
//!
//! 票据文本形如 `sunday2:<base64url({"b":"<body>","s":"<签名>"})>`。旧的 `sunday1:`
//! 票据只在「已配对设备的自动重连」里还有意义：它只表示地址，不代表授权。

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{bail, Context, Result};
use base64::Engine as _;
use iroh::{EndpointAddr, PublicKey, SecretKey, Signature};
use serde::{Deserialize, Serialize};

/// 带签名与有效期的配对票据前缀。
pub const PREFIX: &str = "sunday2:";

/// 一张配对票最多活多久。
///
/// user:“有效期明确（建议 ≤5 分钟）”+(再长就等于把「长期通行证」换个说法；出票方传入的
/// 有效期也会被夹到这个上限)。
pub const MAX_TTL_SECS: u64 = 300;

/// 一次性记录的保留时间：过期票据再多留一会儿，防止时钟回拨导致的「复活」。
const KEEP_USED_AFTER_EXPIRY_SECS: u64 = 3600;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Body {
    /// 出票方的节点 id（必须与 `addr` 的 id 一致）。
    id: String,
    /// 拨号地址。
    addr: EndpointAddr,
    /// 过期时间（Unix 秒）。
    exp: u64,
    /// 一次性随机数。
    nonce: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Envelope {
    /// body 的 base64url；签名覆盖的就是这段字节，校验时按原字节复用。
    b: String,
    /// 十六进制签名。
    s: String,
}

/// 一张已签名、带有效期的配对票。
#[derive(Debug, Clone)]
pub struct PairingTicket {
    pub addr: EndpointAddr,
    pub expires_at: u64,
    pub nonce: String,
    /// 二维码里编码的那段文本。
    pub text: String,
}

pub fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0)
}

pub fn is_pairing_ticket(text: &str) -> bool {
    text.trim().starts_with(PREFIX)
}

/// 32 个十六进制字符的一次性随机数。
///
/// 用节点密钥生成器取随机字节：不额外引 rand，随机性仍然是操作系统提供的。
pub fn new_nonce() -> String {
    let raw = SecretKey::generate().to_bytes();
    hex_encode(&raw[..16])
}

/// 出一张新票。
pub fn issue(
    secret: &SecretKey,
    addr: &EndpointAddr,
    ttl: Duration,
    now: u64,
) -> Result<PairingTicket> {
    let ttl = ttl.as_secs().clamp(1, MAX_TTL_SECS);
    let body = Body {
        id: addr.id.to_string(),
        addr: addr.clone(),
        exp: now + ttl,
        nonce: new_nonce(),
    };
    let bytes = serde_json::to_vec(&body).context("cannot encode the pairing ticket")?;
    let signature = secret.sign(&bytes);
    let envelope = Envelope {
        b: b64(&bytes),
        s: hex_encode(&signature.to_bytes()),
    };
    let text = format!(
        "{PREFIX}{}",
        b64(&serde_json::to_vec(&envelope).context("cannot encode the pairing envelope")?)
    );
    Ok(PairingTicket {
        addr: body.addr,
        expires_at: body.exp,
        nonce: body.nonce,
        text,
    })
}

/// 校验一张票：签名、有效期，以及（可选）它是不是给这台机器的。
///
/// user:“重复使用要被拒绝并给出可读原因”+(所有失败路径都给中文原因，界面和 CLI 直接显示，
/// 用户看到的是「二维码用过了」而不是一句 closed by peer)。
pub fn verify(
    text: &str,
    expected_server: Option<&str>,
    now: u64,
) -> Result<PairingTicket> {
    let trimmed = text.trim();
    let Some(body_text) = trimmed.strip_prefix(PREFIX) else {
        bail!("这不是配对二维码（缺少 {PREFIX} 前缀）");
    };
    let envelope: Envelope = serde_json::from_slice(
        &unb64(body_text).context("配对二维码的内容无法解析")?,
    )
    .context("配对二维码的内容无法解析")?;
    let body_bytes = unb64(&envelope.b).context("配对二维码的正文无法解析")?;
    let body: Body =
        serde_json::from_slice(&body_bytes).context("配对二维码的正文无法解析")?;

    // 签名用票据里那个节点自己的公钥验证：换成别的私钥签的票在这里就过不去。
    let public = PublicKey::from_bytes(body.addr.id.as_bytes())
        .map_err(|_| anyhow::anyhow!("配对二维码里的节点身份不合法"))?;
    let signature_bytes = hex_decode(&envelope.s).context("配对二维码的签名格式不对")?;
    if signature_bytes.len() != Signature::LENGTH {
        bail!("配对二维码的签名格式不对");
    }
    let mut raw = [0u8; Signature::LENGTH];
    raw.copy_from_slice(&signature_bytes);
    public
        .verify(&body_bytes, &Signature::from_bytes(&raw))
        .map_err(|_| anyhow::anyhow!("配对二维码签名不正确，可能被伪造或篡改"))?;

    if let Some(expected) = expected_server {
        if body.id != expected {
            bail!("这张配对二维码不是给这台电脑的");
        }
    }
    if body.exp <= now {
        bail!("配对二维码已过期（有效期最多 {MAX_TTL_SECS} 秒），请在电脑上重新生成");
    }
    Ok(PairingTicket {
        addr: body.addr,
        expires_at: body.exp,
        nonce: body.nonce,
        text: trimmed.to_owned(),
    })
}

/// 一次性消费记录，落盘在出票方的数据目录里。
///
/// user:“用过即失效”+(只放在内存里的话，传输进程重启一次，同一张码又能用；所以和可信
/// 名单一样写文件，进程重启后仍然记得哪些随机数已经用过)。
#[derive(Debug, Default, Clone, Serialize, Deserialize)]
pub struct PairingGrants {
    /// nonce → 票据过期时间。
    #[serde(default)]
    used: BTreeMap<String, u64>,
    #[serde(skip)]
    path: PathBuf,
}

impl PairingGrants {
    pub fn load(dir: &Path) -> Result<Self> {
        let path = dir.join("p2p-pairing.json");
        if !path.exists() {
            return Ok(Self {
                used: BTreeMap::new(),
                path,
            });
        }
        let text = std::fs::read_to_string(&path).context("cannot read p2p-pairing.json")?;
        let mut grants: Self =
            serde_json::from_str(&text).context("p2p-pairing.json is not valid JSON")?;
        grants.path = path;
        Ok(grants)
    }

    pub fn save(&self) -> Result<()> {
        if self.path.as_os_str().is_empty() {
            return Ok(());
        }
        let text = serde_json::to_string_pretty(self).context("cannot encode the pairing grants")?;
        let temporary = self.path.with_extension("tmp");
        std::fs::write(&temporary, text).context("cannot write the pairing grants")?;
        std::fs::rename(&temporary, &self.path).context("cannot install the pairing grants")?;
        Ok(())
    }

    pub fn is_used(&self, nonce: &str) -> bool {
        self.used.contains_key(nonce)
    }

    /// 用掉一张票。返回 `false` 表示它已经被用过（重复使用要被拒绝）。
    pub fn consume(&mut self, nonce: &str, expires_at: u64) -> bool {
        if self.used.contains_key(nonce) {
            return false;
        }
        self.used.insert(nonce.to_owned(), expires_at);
        true
    }

    /// 作废一张还没用过的票（重新生成二维码时，旧码立刻失效）。
    pub fn retire(&mut self, nonce: &str, expires_at: u64) {
        self.used.insert(nonce.to_owned(), expires_at);
    }

    /// 清理早就过期的记录，文件不会无限长大。
    pub fn prune(&mut self, now: u64) {
        let horizon = now.saturating_sub(KEEP_USED_AFTER_EXPIRY_SECS);
        self.used
            .retain(|_, expires_at| *expires_at >= horizon.min(now));
    }
}

fn b64(bytes: &[u8]) -> String {
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(bytes)
}

fn unb64(text: &str) -> Result<Vec<u8>> {
    base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(text)
        .context("not base64url")
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
    for pair in text.as_bytes().chunks(2) {
        let high = (pair[0] as char).to_digit(16).context("bad hex digit")? as u8;
        let low = (pair[1] as char).to_digit(16).context("bad hex digit")? as u8;
        out.push((high << 4) | low);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use iroh::{EndpointId, TransportAddr};

    fn sample_addr(secret: &SecretKey) -> EndpointAddr {
        let mut addrs = std::collections::BTreeSet::new();
        addrs.insert(TransportAddr::Ip("127.0.0.1:4242".parse().unwrap()));
        EndpointAddr {
            id: EndpointId::from(secret.public()),
            addrs,
        }
    }

    /// user:“扫码即可完成配对”+(一张正常票据应当能解出地址，并且带着还没用过的随机数)。
    #[test]
    fn a_fresh_ticket_verifies_and_carries_its_address() {
        let secret = SecretKey::generate();
        let addr = sample_addr(&secret);
        let ticket = issue(&secret, &addr, Duration::from_secs(300), 1_000).unwrap();
        assert!(is_pairing_ticket(&ticket.text));
        let parsed = verify(&ticket.text, Some(&addr.id.to_string()), 1_100).unwrap();
        assert_eq!(parsed.addr, addr);
        assert_eq!(parsed.nonce, ticket.nonce);
        assert_eq!(parsed.expires_at, 1_300);
    }

    /// user:“过期后必须重新生成”+(过了有效期就是不能用，且原因要说人话)。
    #[test]
    fn an_expired_ticket_is_refused_with_a_readable_reason() {
        let secret = SecretKey::generate();
        let addr = sample_addr(&secret);
        let ticket = issue(&secret, &addr, Duration::from_secs(300), 1_000).unwrap();
        let error = verify(&ticket.text, None, 1_301).unwrap_err().to_string();
        assert!(error.contains("已过期"), "unexpected reason: {error}");
    }

    /// 有效期再长也会被夹到 5 分钟。
    #[test]
    fn the_ttl_is_capped_at_five_minutes() {
        let secret = SecretKey::generate();
        let addr = sample_addr(&secret);
        let ticket = issue(&secret, &addr, Duration::from_secs(86_400), 1_000).unwrap();
        assert_eq!(ticket.expires_at, 1_000 + MAX_TTL_SECS);
    }

    /// user:“票据不可伪造”+(改一个字节就验不过)。
    #[test]
    fn a_tampered_ticket_does_not_verify() {
        let secret = SecretKey::generate();
        let addr = sample_addr(&secret);
        let ticket = issue(&secret, &addr, Duration::from_secs(300), 1_000).unwrap();
        let mut tampered = ticket.text.clone();
        let last = tampered.pop().unwrap();
        tampered.push(if last == 'A' { 'B' } else { 'A' });
        assert!(verify(&tampered, None, 1_100).is_err());
    }

    /// 别人用自己的私钥出的票，不能被当成这台机器的授权。
    #[test]
    fn a_ticket_signed_by_another_key_is_not_accepted_for_this_machine() {
        let their_secret = SecretKey::generate();
        let their_addr = sample_addr(&their_secret);
        let ticket = issue(&their_secret, &their_addr, Duration::from_secs(300), 1_000).unwrap();
        // 票据本身是合法的（签名与它自己的节点 id 对得上）……
        assert!(verify(&ticket.text, None, 1_100).is_ok());
        // ……但它不是给「我」的。
        let mine = SecretKey::generate();
        let error = verify(&ticket.text, Some(&mine.public().to_string()), 1_100)
            .unwrap_err()
            .to_string();
        assert!(error.contains("不是给这台电脑"), "unexpected reason: {error}");
    }

    /// user:“用过即失效”“重复使用要被拒绝”+(第二次消费同一个随机数必须失败，而且落盘后仍然失败)。
    #[test]
    fn a_nonce_can_only_be_consumed_once_even_after_a_restart() {
        let dir = std::env::temp_dir().join(format!("sunday-pair-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let nonce = new_nonce();
        let mut grants = PairingGrants::load(&dir).unwrap();
        assert!(grants.consume(&nonce, now() + 300));
        grants.save().unwrap();

        // 进程重启：重新从盘上读。
        let mut reloaded = PairingGrants::load(&dir).unwrap();
        assert!(reloaded.is_used(&nonce));
        assert!(!reloaded.consume(&nonce, now() + 300));
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 重新生成二维码时旧码立刻作废，不需要等它自己过期。
    #[test]
    fn retiring_a_ticket_makes_it_unusable() {
        let mut grants = PairingGrants::default();
        let nonce = new_nonce();
        grants.retire(&nonce, 1_000);
        assert!(!grants.consume(&nonce, 1_000));
    }

    /// 过期的消费记录会被清掉，文件不会无限长大。
    #[test]
    fn pruning_drops_records_that_expired_long_ago() {
        let mut grants = PairingGrants::default();
        grants.consume("old", 1_000);
        grants.consume("fresh", 100_000);
        grants.prune(100_000);
        assert!(!grants.is_used("old"));
        assert!(grants.is_used("fresh"));
    }
}
