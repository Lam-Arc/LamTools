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

const MAX_ANSWER_BYTES: usize = 128 * 1024 * 1024;
const READ_TIMEOUT: Duration = Duration::from_secs(120);

/// A tiny HTTP/1.1 client, on purpose.
///
/// Core listens on loopback, so TLS and connection pooling buy nothing here, and a raw
/// request keeps the dependency list of the transport at zero. `Connection: close` makes
/// the answer end at EOF, which is the whole parsing strategy.
///
/// user:“远程模式下附件发不出去、图片预览是坏的”+(界面走的是 multipart 和图片字节，
/// 以前这一层只拼 JSON，二进制一律被当文本毁掉。附件、预览、素材库要能用，就必须保留
/// 原始字节和调用方给的 Content-Type，所以这里只做字节透传，另有一个 JSON 便捷入口)。
pub fn call_core(
    host: &str,
    port: u16,
    token: &str,
    method: &str,
    path: &str,
    body: Option<&Value>,
) -> Result<(u16, Value)> {
    let payload = body.map(|value| value.to_string()).unwrap_or_default();
    let headers: Vec<(String, String)> = if payload.is_empty() {
        Vec::new()
    } else {
        vec![("Content-Type".to_owned(), "application/json".to_owned())]
    };
    let bytes = if payload.is_empty() {
        None
    } else {
        Some(payload.into_bytes())
    };
    let (status, _headers, raw) =
        call_core_raw(host, port, token, method, path, &headers, bytes)?;
    let value = if raw.is_empty() {
        Value::Null
    } else {
        // 不是 JSON 的回答原样带回去，让调用方能看见它到底是什么。
        serde_json::from_slice(&raw).unwrap_or_else(|_| {
            serde_json::json!({ "raw": String::from_utf8_lossy(&raw) })
        })
    };
    Ok((status, value))
}

/// 原样转发一个请求：调用方给什么头、什么字节，Core 就收到什么，回答也按字节回来。
///
/// 返回值是 `(状态码, 响应头, 响应体)`。响应头保留，是因为预览和下载要靠 Content-Type
/// 判断这是图片、PDF 还是 JSON。
pub fn call_core_raw(
    host: &str,
    port: u16,
    token: &str,
    method: &str,
    path: &str,
    headers: &[(String, String)],
    body: Option<Vec<u8>>,
) -> Result<(u16, Vec<(String, String)>, Vec<u8>)> {
    let mut stream = TcpStream::connect((host, port))
        .with_context(|| format!("cannot reach the core at {host}:{port}"))?;
    stream.set_read_timeout(Some(READ_TIMEOUT)).ok();
    stream.set_write_timeout(Some(Duration::from_secs(30))).ok();

    let mut request = format!("{method} {path} HTTP/1.1\r\nHost: {host}:{port}\r\n");
    if !token.is_empty() {
        request.push_str(&format!("Authorization: Bearer {token}\r\n"));
    }
    request.push_str("Connection: close\r\n");
    let mut has_type = false;
    for (name, value) in headers {
        // 这几个头由这一层决定，调用方给的值会破坏解析或泄露内部地址。
        let lower = name.to_ascii_lowercase();
        if matches!(
            lower.as_str(),
            "host" | "connection" | "content-length" | "authorization" | "transfer-encoding"
        ) {
            continue;
        }
        if lower == "content-type" {
            has_type = true;
        }
        request.push_str(&format!("{name}: {value}\r\n"));
    }
    if let Some(bytes) = body.as_ref() {
        if !has_type {
            request.push_str("Content-Type: application/octet-stream\r\n");
        }
        request.push_str(&format!("Content-Length: {}\r\n", bytes.len()));
    }
    request.push_str("\r\n");
    stream
        .write_all(request.as_bytes())
        .context("cannot write the request to the core")?;
    if let Some(bytes) = body.as_ref() {
        stream
            .write_all(bytes)
            .context("cannot write the request body to the core")?;
    }

    let mut raw = Vec::new();
    // 先限流再读，避免一个异常的大回答把内存吃光。
    let mut limited = Read::take(&stream, MAX_ANSWER_BYTES as u64);
    limited
        .read_to_end(&mut raw)
        .context("cannot read the answer from the core")?;
    let (status, response_headers, body_bytes) = split_response(&raw)?;
    let body_bytes = if is_chunked(&response_headers) {
        decode_chunked(body_bytes)?
    } else {
        body_bytes.to_vec()
    };
    Ok((status, response_headers, body_bytes))
}

fn split_response(raw: &[u8]) -> Result<(u16, Vec<(String, String)>, &[u8])> {
    let split = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .context("Core 的回答没有头部结尾")?;
    let head = String::from_utf8_lossy(&raw[..split]);
    let mut status = 0u16;
    let mut headers = Vec::new();
    for (index, line) in head.lines().enumerate() {
        if index == 0 {
            status = line
                .split_whitespace()
                .nth(1)
                .and_then(|code| code.parse().ok())
                .unwrap_or(0);
            continue;
        }
        if let Some((name, value)) = line.split_once(':') {
            headers.push((name.trim().to_owned(), value.trim().to_owned()));
        }
    }
    Ok((status, headers, &raw[split + 4..]))
}

fn is_chunked(headers: &[(String, String)]) -> bool {
    headers.iter().any(|(name, value)| {
        name.eq_ignore_ascii_case("transfer-encoding") && value.to_ascii_lowercase().contains("chunked")
    })
}

/// 分块传输的解码。流式接口在 `Connection: close` 下也可能用 chunked，原样交给界面会
/// 得到一坨带长度前缀的碎片，所以这里先拆干净。
fn decode_chunked(raw: &[u8]) -> Result<Vec<u8>> {
    let mut out = Vec::with_capacity(raw.len());
    let mut index = 0usize;
    loop {
        let line_end = raw[index..]
            .windows(2)
            .position(|window| window == b"\r\n")
            .context("分块回答缺少长度行")?
            + index;
        let line = String::from_utf8_lossy(&raw[index..line_end]);
        let size_text = line.split(';').next().unwrap_or("").trim();
        let size = usize::from_str_radix(size_text, 16).context("分块回答的长度不是十六进制")?;
        index = line_end + 2;
        if size == 0 {
            return Ok(out);
        }
        if index + size > raw.len() {
            bail!("分块回答被截断");
        }
        out.extend_from_slice(&raw[index..index + size]);
        index += size;
        if raw.get(index..index + 2) == Some(b"\r\n") {
            index += 2;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_status_headers_and_body() {
        let raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 7\r\n\r\n{\"a\":1}";
        let (status, headers, body) = split_response(raw).unwrap();
        assert_eq!(status, 200);
        assert!(headers
            .iter()
            .any(|(name, value)| name.eq_ignore_ascii_case("content-type") && value == "application/json"));
        assert_eq!(body, b"{\"a\":1}");
    }

    #[test]
    fn decodes_a_chunked_body() {
        let raw = b"5\r\n{\"a\":\r\n2\r\n1}\r\n0\r\n\r\n";
        assert_eq!(decode_chunked(raw).unwrap(), b"{\"a\":1}");
    }

    #[test]
    fn binary_bodies_survive_untouched() {
        // user:“远程模式下图片预览是坏的”+(0x89 和 0x00 在“当文本解码”的方案里会坏掉，
        // 这里固定住：二进制回答必须原样到达调用方)。
        let mut raw = b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n\r\n".to_vec();
        raw.extend_from_slice(&[0x89, 0x50, 0x4e, 0x47, 0x00, 0x1a, 0x0a]);
        let (status, headers, body) = split_response(&raw).unwrap();
        assert_eq!(status, 200);
        assert_eq!(body, &[0x89, 0x50, 0x4e, 0x47, 0x00, 0x1a, 0x0a]);
        assert!(headers
            .iter()
            .any(|(name, value)| name.eq_ignore_ascii_case("content-type") && value == "image/png"));
    }
}
