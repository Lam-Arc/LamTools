//! Pairing tickets.
//!
//! user:“设备配对：支持二维码、配对码等简单方式”+(票据本身就是二维码要编码的文本，
//! 也可以直接复制粘贴；二维码只是它的另一种呈现，不需要第二套数据)。
//!
//! What a ticket carries: the peer's endpoint id plus whatever addressing is known at the
//! time (a relay URL and/or local addresses). iroh also publishes endpoint addresses in
//! DNS, so a ticket that only carries the id still dials — the extra addressing just makes
//! the first attempt faster.

use anyhow::{bail, Context, Result};
use base64::Engine;
use iroh::EndpointAddr;

const PREFIX: &str = "sunday1:";

/// The text a QR code holds.
pub fn encode_ticket(addr: &EndpointAddr) -> Result<String> {
    let json = serde_json::to_vec(addr).context("cannot encode the endpoint address")?;
    Ok(format!(
        "{PREFIX}{}",
        base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(json)
    ))
}

/// 任意票据 → 对端地址。
///
/// user:“扫码即可完成配对”+(扫到的是 `sunday2:` 配对票，它既带地址也带授权；已配对设备
/// 重连时手里是 `sunday1:` 地址票。两条路只在这里分叉一次，上层不用关心)。
pub fn decode_any_ticket(text: &str) -> Result<EndpointAddr> {
    let trimmed = text.trim();
    if crate::pair::is_pairing_ticket(trimmed) {
        return Ok(crate::pair::verify(trimmed, None, crate::pair::now())?.addr);
    }
    decode_ticket(trimmed)
}

pub fn decode_ticket(text: &str) -> Result<EndpointAddr> {
    let trimmed = text.trim();
    let body = trimmed.strip_prefix(PREFIX).unwrap_or(trimmed);
    if body.is_empty() {
        bail!("配对票据是空的");
    }
    let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(body)
        .context("配对票据不是合法的 base64")?;
    serde_json::from_slice(&bytes).context("配对票据内容无法解析")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ticket_round_trip_needs_a_real_endpoint_address() {
        // 这段只验证前缀与解码失败路径；真正的往返在 link 的集成测试里用真实地址跑。
        assert!(decode_ticket("sunday1:").is_err());
        assert!(decode_ticket("not-a-ticket").is_err());
    }
}
