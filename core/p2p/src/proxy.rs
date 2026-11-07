//! Forwarding a remote call to the local Core.
//!
//! user:“优先复用现有 Core API，不重新实现业务逻辑”+(远程过来的 method/path 原样打到
//! 本机 Core 的 REST 端口，答案原样回去；这一层不解释任何业务字段)。
//!
//! Only loopback is allowed: the whole point of the tunnel is that the Core stays bound
//! to 127.0.0.1 and this process is the single door.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use serde_json::Value;

const MAX_ANSWER_BYTES: usize = 32 * 1024 * 1024;

/// A tiny HTTP/1.1 client, on purpose.
///
/// Core listens on loopback, so TLS and connection pooling buy nothing here, and a raw
/// request keeps the dependency list of the transport at zero. `Connection: close` makes
/// the answer end at EOF, which is the whole parsing strategy.
pub fn call_core(
    host: &str,
    port: u16,
    token: &str,
    method: &str,
    path: &str,
    body: Option<&Value>,
) -> Result<(u16, Value)> {
    let payload = body.map(|value| value.to_string()).unwrap_or_default();
    let mut stream = TcpStream::connect((host, port))
        .with_context(|| format!("cannot reach the core at {host}:{port}"))?;
    stream.set_read_timeout(Some(Duration::from_secs(120))).ok();
    stream.set_write_timeout(Some(Duration::from_secs(30))).ok();

    let mut request = format!(
        "{method} {path} HTTP/1.1\r\nHost: {host}:{port}\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n"
    );
    if !payload.is_empty() {
        request.push_str("Content-Type: application/json\r\n");
        request.push_str(&format!("Content-Length: {}\r\n", payload.len()));
    }
    request.push_str("\r\n");
    request.push_str(&payload);
    stream
        .write_all(request.as_bytes())
        .context("cannot write the request to the core")?;

    let mut raw = Vec::new();
    stream
        .read_to_end(&mut raw)
        .context("cannot read the answer from the core")?;
    parse_response(&raw)
}

fn parse_response(raw: &[u8]) -> Result<(u16, Value)> {
    if raw.len() > MAX_ANSWER_BYTES {
        bail!("Core 的回答太大");
    }
    let split = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .context("Core 的回答没有头部结尾")?;
    let head = String::from_utf8_lossy(&raw[..split]);
    let mut status = 0u16;
    for line in head.lines() {
        if let Some(rest) = line.strip_prefix("HTTP/1.1 ").or_else(|| line.strip_prefix("HTTP/1.0 ")) {
            status = rest
                .split_whitespace()
                .next()
                .and_then(|code| code.parse().ok())
                .unwrap_or(0);
            break;
        }
    }
    let body = &raw[split + 4..];
    let value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(body).unwrap_or_else(|_| {
            serde_json::json!({ "raw": String::from_utf8_lossy(body) })
        })
    };
    Ok((status, value))
}
