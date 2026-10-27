// user:“本机加速层 你学习一下呗…它该抄就抄”+(照 FastGithub/Watt Toolkit：本地 HTTP CONNECT 代理，命中常用域名时用 DoH 选 IP 直连，TLS 原样透传)。
use crate::state::Reply;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    net::{IpAddr, SocketAddr},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tokio::{
    io::{copy_bidirectional, AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    task::{JoinHandle, JoinSet},
};

const MAX_HEADER: usize = 16 * 1024;
const CONNECT_TIMEOUT: Duration = Duration::from_secs(4);
const DOH_TIMEOUT: Duration = Duration::from_secs(3);
const FIRST_BYTE_TIMEOUT: Duration = Duration::from_secs(2);
const MAX_CANDIDATES: usize = 8;
// user:“加速和代理要不要改成智能进行，先想清楚加速和翻墙的原理”+(只按连接结果做确定性分流：直连失败后记住域名，后续优先走线路)。
const PROXY_PREFERENCE_TTL: Duration = Duration::from_secs(30 * 60);
const MAX_PROXY_PREFERENCES: usize = 512;
// user:“那你试了吗？能连上吗？比如 mod n 网”+(实测国内网络会拦 Cloudflare/Google DoH，补上阿里与 DNSPod，多个 DoH 并发取答案)。
const DOH_ENDPOINTS: &[&str] = &[
    "https://223.5.5.5/resolve",
    "https://doh.pub/dns-query",
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/resolve",
];

pub struct Accelerator {
    task: Option<JoinHandle<()>>,
    pub port: u16,
    pub fallback_proxy: Option<u16>,
    preferred: Arc<Mutex<HashMap<String, Instant>>>,
}
impl Default for Accelerator {
    fn default() -> Self {
        Self::new()
    }
}
impl Accelerator {
    pub fn new() -> Self {
        Self {
            task: None,
            port: 0,
            fallback_proxy: None,
            preferred: Arc::new(Mutex::new(HashMap::new())),
        }
    }
    pub fn status(&self) -> Value {
        json!({
            "running": self.task.is_some(),
            "port": self.port,
            "fallback_proxy": self.fallback_proxy,
            "proxy_preferred": self.preferred.lock().map(|rows| rows.len()).unwrap_or(0),
            "mode": "local_direct",
            "note": "常用域名用 DoH 选 IP 直连；直连失败后回退线路并记住该域名。"
        })
    }
    pub async fn start(&mut self, fallback_proxy: Option<u16>) -> Reply {
        if self.task.is_some() {
            return Ok(self.status());
        }
        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .map_err(|error| format!("本机加速端口不可用：{error}"))?;
        let port = listener
            .local_addr()
            .map_err(|error| error.to_string())?
            .port();
        let preferred = self.preferred.clone();
        let task = tokio::spawn(async move {
            loop {
                match listener.accept().await {
                    Ok((client, _)) => {
                        tokio::spawn(handle(client, fallback_proxy, preferred.clone()));
                    }
                    Err(_) => tokio::time::sleep(Duration::from_millis(80)).await,
                }
            }
        });
        self.task = Some(task);
        self.port = port;
        self.fallback_proxy = fallback_proxy;
        Ok(self.status())
    }
    pub fn stop(&mut self) {
        if let Some(task) = self.task.take() {
            task.abort();
        }
        self.port = 0;
        self.fallback_proxy = None;
    }
}
async fn handle(
    mut client: TcpStream,
    fallback: Option<u16>,
    preferred: Arc<Mutex<HashMap<String, Instant>>>,
) {
    let Some((header, method, authority)) = read_headers(&mut client).await else {
        return;
    };
    if method != "CONNECT" {
        forward_raw(client, header, fallback).await;
        return;
    }
    let Ok((host, port)) = parse_authority(&authority) else {
        respond(&mut client, "400 Bad Request").await;
        return;
    };
    let common = crate::engines::is_common_acceleration_host(&host);
    if common && fallback.is_some() && proxy_preferred(&preferred, &host) {
        if let Some(proxy_port) = fallback {
            if tunnel_via_proxy(&mut client, &header, proxy_port)
                .await
                .is_ok()
            {
                remember_proxy(&preferred, &host);
                return;
            }
        }
        forget_proxy(&preferred, &host);
    }
    // 常用域名加速失败时继续走下面的代理/系统解析，不能比不开加速更差。
    if common {
        if let Ok(upstream) = connect_accelerated(&host, port).await {
            if client
                .write_all(
                    b"HTTP/1.1 200 Connection Established\r\nProxy-Agent: Sunday-Network\r\n\r\n",
                )
                .await
                .is_ok()
            {
                relay_accelerated(
                    &mut client,
                    upstream,
                    fallback,
                    &header,
                    &preferred,
                    &host,
                )
                .await;
            }
            return;
        }
    }
    if let Some(proxy_port) = fallback {
        if tunnel_via_proxy(&mut client, &header, proxy_port)
            .await
            .is_ok()
        {
            if common {
                remember_proxy(&preferred, &host);
            }
            return;
        }
    }
    match TcpStream::connect((host.as_str(), port)).await {
        Ok(mut upstream) => {
            if client
                .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                .await
                .is_ok()
            {
                let _ = copy_bidirectional(&mut client, &mut upstream).await;
            }
        }
        Err(_) => respond(&mut client, "502 Bad Gateway").await,
    }
}
fn proxy_preferred(memory: &Mutex<HashMap<String, Instant>>, host: &str) -> bool {
    memory
        .lock()
        .map(|rows| {
            rows.get(host)
                .is_some_and(|seen| seen.elapsed() < PROXY_PREFERENCE_TTL)
        })
        .unwrap_or(false)
}
fn remember_proxy(memory: &Mutex<HashMap<String, Instant>>, host: &str) {
    let Ok(mut rows) = memory.lock() else {
        return;
    };
    rows.insert(host.to_string(), Instant::now());
    if rows.len() > MAX_PROXY_PREFERENCES {
        rows.retain(|_, seen| seen.elapsed() < PROXY_PREFERENCE_TTL);
    }
}
fn forget_proxy(memory: &Mutex<HashMap<String, Instant>>, host: &str) {
    if let Ok(mut rows) = memory.lock() {
        rows.remove(host);
    }
}
async fn read_headers(client: &mut TcpStream) -> Option<(Vec<u8>, String, String)> {
    let mut buffer = Vec::new();
    let mut chunk = [0u8; 1024];
    loop {
        let read = client.read(&mut chunk).await.ok()?;
        if read == 0 {
            return None;
        }
        buffer.extend_from_slice(&chunk[..read]);
        if buffer.len() > MAX_HEADER {
            return None;
        }
        if let Some(index) = buffer.windows(4).position(|window| window == b"\r\n\r\n") {
            let text = String::from_utf8_lossy(&buffer[..index + 4]).to_string();
            let mut parts = text.lines().next()?.split_whitespace();
            let method = parts.next()?.to_ascii_uppercase();
            let authority = parts.next()?.to_string();
            return Some((buffer, method, authority));
        }
    }
}
async fn forward_raw(mut client: TcpStream, header: Vec<u8>, fallback: Option<u16>) {
    let Some(proxy_port) = fallback else {
        respond(&mut client, "502 Bad Gateway").await;
        return;
    };
    match TcpStream::connect(("127.0.0.1", proxy_port)).await {
        Ok(mut upstream) => {
            if upstream.write_all(&header).await.is_ok() {
                let _ = copy_bidirectional(&mut client, &mut upstream).await;
            }
        }
        Err(_) => respond(&mut client, "502 Bad Gateway").await,
    }
}
// user:“那你试了吗？能连上吗？比如 mod n 网”+(DNS 被污染时 TCP 能连上但 TLS 被重置，首包失败就改走已开启的线路)。
async fn relay_accelerated(
    client: &mut TcpStream,
    mut upstream: TcpStream,
    fallback: Option<u16>,
    header: &[u8],
    preferred: &Mutex<HashMap<String, Instant>>,
    host: &str,
) {
    let mut first = [0u8; 8192];
    let read = match tokio::time::timeout(Duration::from_secs(10), client.read(&mut first)).await {
        Ok(Ok(read)) if read > 0 => read,
        _ => return,
    };
    if upstream.write_all(&first[..read]).await.is_err() {
        return;
    }
    let mut probe = [0u8; 1];
    match tokio::time::timeout(FIRST_BYTE_TIMEOUT, upstream.read(&mut probe)).await {
        Ok(Ok(read)) if read > 0 => {
            if client.write_all(&probe[..read]).await.is_ok() {
                let _ = copy_bidirectional(client, &mut upstream).await;
            }
        }
        _ => {
            let Some(proxy_port) = fallback else {
                return;
            };
            let Ok(mut proxy) = open_proxy_tunnel(proxy_port, header).await else {
                return;
            };
            if proxy.write_all(&first[..read]).await.is_ok() {
                remember_proxy(preferred, host);
                let _ = copy_bidirectional(client, &mut proxy).await;
            }
        }
    }
}
async fn open_proxy_tunnel(proxy_port: u16, header: &[u8]) -> Result<TcpStream, String> {
    let mut upstream = TcpStream::connect(("127.0.0.1", proxy_port))
        .await
        .map_err(|_| "上游代理不可用")?;
    upstream
        .write_all(header)
        .await
        .map_err(|_| "上游代理写入失败")?;
    let mut response = Vec::new();
    let mut chunk = [0u8; 1024];
    loop {
        let read = upstream
            .read(&mut chunk)
            .await
            .map_err(|_| "上游代理响应失败")?;
        if read == 0 {
            return Err("上游代理断开".into());
        }
        response.extend_from_slice(&chunk[..read]);
        if response.len() > MAX_HEADER {
            return Err("上游代理响应过大".into());
        }
        if response.windows(4).any(|window| window == b"\r\n\r\n") {
            break;
        }
    }
    let status = String::from_utf8_lossy(&response);
    if !(status.starts_with("HTTP/1.1 200") || status.starts_with("HTTP/1.0 200")) {
        return Err("上游代理拒绝连接".into());
    }
    Ok(upstream)
}
async fn tunnel_via_proxy(
    client: &mut TcpStream,
    header: &[u8],
    proxy_port: u16,
) -> Result<(), String> {
    let mut upstream = open_proxy_tunnel(proxy_port, header).await?;
    client
        .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        .await
        .map_err(|_| "客户端写入失败")?;
    // 200 已经发给客户端，后续拷贝失败也只能结束这条隧道，不能再回退并写第二个 200。
    let _ = copy_bidirectional(client, &mut upstream).await;
    Ok(())
}
async fn connect_accelerated(host: &str, port: u16) -> Result<TcpStream, String> {
    let mut addresses = resolve_doh(host).await;
    if addresses.is_empty() {
        addresses = tokio::net::lookup_host((host, port))
            .await
            .map_err(|_| "解析失败")?
            .map(|row| row.ip())
            .collect();
    }
    let mut seen = std::collections::HashSet::new();
    addresses.retain(|ip| usable_ip(*ip) && seen.insert(*ip));
    addresses.truncate(MAX_CANDIDATES);
    if addresses.is_empty() {
        return Err("没有可用地址".into());
    }
    let mut tasks = JoinSet::new();
    for address in addresses {
        tasks.spawn(async move {
            tokio::time::timeout(
                CONNECT_TIMEOUT,
                TcpStream::connect(SocketAddr::new(address, port)),
            )
            .await
            .ok()
            .and_then(|result| result.ok())
        });
    }
    while let Some(result) = tasks.join_next().await {
        if let Ok(Some(stream)) = result {
            tasks.abort_all();
            return Ok(stream);
        }
    }
    Err("候选地址均不可达".into())
}
fn usable_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            !(v4.is_unspecified()
                || v4.is_loopback()
                || v4.is_multicast()
                || v4.is_broadcast()
                || v4.octets()[0] == 0)
        }
        IpAddr::V6(v6) => {
            if let Some(v4) = v6.to_ipv4_mapped() {
                return usable_ip(IpAddr::V4(v4));
            }
            !(v6.is_unspecified()
                || v6.is_loopback()
                || v6.is_multicast()
                || (v6.segments()[0] & 0xffc0) == 0xfe80)
        }
    }
}
async fn query_doh(client: &reqwest::Client, endpoint: &str, host: &str) -> Vec<IpAddr> {
    let Ok(mut url) = reqwest::Url::parse(endpoint) else {
        return Vec::new();
    };
    url.query_pairs_mut()
        .append_pair("name", host)
        .append_pair("type", "A");
    let Ok(response) = client
        .get(url)
        .header("Accept", "application/dns-json")
        .send()
        .await
    else {
        return Vec::new();
    };
    if !response.status().is_success() {
        return Vec::new();
    }
    let Ok(value) = response.json::<Value>().await else {
        return Vec::new();
    };
    value["Answer"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|row| row["type"].as_u64() == Some(1))
        .filter_map(|row| row["data"].as_str())
        .filter_map(|text| text.parse().ok())
        .collect()
}
async fn resolve_doh(host: &str) -> Vec<IpAddr> {
    let Ok(client) = reqwest::Client::builder()
        .no_proxy()
        .timeout(DOH_TIMEOUT)
        .build()
    else {
        return Vec::new();
    };
    let mut tasks = JoinSet::new();
    for endpoint in DOH_ENDPOINTS {
        let client = client.clone();
        let host = host.to_string();
        tasks.spawn(async move { query_doh(&client, endpoint, &host).await });
    }
    let mut addresses = Vec::new();
    while let Some(result) = tasks.join_next().await {
        if let Ok(mut rows) = result {
            addresses.append(&mut rows);
        }
        if addresses.len() >= 2 {
            tasks.abort_all();
            break;
        }
    }
    addresses
}
fn parse_authority(value: &str) -> Result<(String, u16), String> {
    let value = value.trim();
    if value.is_empty() {
        return Err("缺少目标地址".into());
    }
    let (host, port) = if let Some(rest) = value.strip_prefix('[') {
        let end = rest.find(']').ok_or("IPv6 地址缺少 ]")?;
        let host = &rest[..end];
        let port = rest[end + 1..]
            .strip_prefix(':')
            .map(|value| value.parse::<u16>().map_err(|_| "端口无效"))
            .transpose()?
            .unwrap_or(443);
        (host.to_string(), port)
    } else if let Some((host, port)) = value.rsplit_once(':') {
        if host.contains(':') {
            return Err("IPv6 地址需要加方括号".into());
        }
        (host.to_string(), port.parse::<u16>().map_err(|_| "端口无效")?)
    } else {
        (value.to_string(), 443)
    };
    crate::observe::validate_host(&host)?;
    if port == 0 {
        return Err("端口无效".into());
    }
    Ok((host, port))
}
async fn respond(client: &mut TcpStream, status: &str) {
    let text = format!("HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
    let _ = client.write_all(text.as_bytes()).await;
    let _ = client.shutdown().await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn common_hosts_match_suffixes_but_not_lookalikes() {
        // user:“本机加速层 你学习一下呗…它该抄就抄”+(照 FastGithub 的域名匹配：精确或子域名)。
        assert!(crate::engines::is_common_acceleration_host("github.com"));
        assert!(crate::engines::is_common_acceleration_host("api.github.com"));
        assert!(crate::engines::is_common_acceleration_host("github.com."));
        assert!(!crate::engines::is_common_acceleration_host("evilgithub.com"));
        assert!(!crate::engines::is_common_acceleration_host("github.com.evil"));
        assert!(crate::engines::is_common_acceleration_host("huggingface.co"));
    }
    #[test]
    fn rejects_resolver_answers_that_point_back_to_this_machine() {
        // user:“那你试了吗？能连上吗？比如 mod n 网”+(实测路由器会把被拦域名解析到 127.0.0.1，必须过滤掉这些假地址)。
        assert!(!usable_ip("127.0.0.1".parse().unwrap()));
        assert!(!usable_ip("127.8.8.8".parse().unwrap()));
        assert!(!usable_ip("0.0.0.0".parse().unwrap()));
        assert!(!usable_ip("224.0.0.1".parse().unwrap()));
        assert!(!usable_ip("::1".parse().unwrap()));
        assert!(!usable_ip("fe80::1".parse().unwrap()));
        assert!(!usable_ip("::ffff:127.0.0.1".parse().unwrap()));
        assert!(usable_ip("140.82.113.4".parse().unwrap()));
        assert!(usable_ip("2606:4700::6810:ca36".parse().unwrap()));
    }
    #[test]
    fn proxy_preference_can_be_remembered_and_forgotten() {
        // user:“加速和代理要不要改成智能进行”+(回退成功的域名下次优先走线路；线路失败时忘掉，允许重新直连)。
        let memory = Mutex::new(HashMap::new());
        assert!(!proxy_preferred(&memory, "github.com"));
        remember_proxy(&memory, "github.com");
        assert!(proxy_preferred(&memory, "github.com"));
        assert!(!proxy_preferred(&memory, "api.github.com"));
        forget_proxy(&memory, "github.com");
        assert!(!proxy_preferred(&memory, "github.com"));
    }
    #[test]
    fn connect_authority_parses_ipv4_ipv6_and_default_port() {
        assert_eq!(
            parse_authority("github.com:443").unwrap(),
            ("github.com".to_string(), 443)
        );
        assert_eq!(
            parse_authority("github.com").unwrap(),
            ("github.com".to_string(), 443)
        );
        assert_eq!(
            parse_authority("[::1]:8443").unwrap(),
            ("::1".to_string(), 8443)
        );
        assert!(parse_authority("github.com:0").is_err());
        assert!(parse_authority("bad host:443").is_err());
    }
}
