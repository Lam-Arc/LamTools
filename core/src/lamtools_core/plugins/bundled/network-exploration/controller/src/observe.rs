// user:“实现这个插件，也正好实验我们的新插件架构”+(诊断仅报告真实测量，命令参数不经过 shell 拼接)。
use crate::{
    powershell,
    state::{Controller, Reply},
};
use serde_json::{json, Value};
use std::{
    net::IpAddr,
    time::{Duration, Instant},
};

pub fn validate_host(host: &str) -> Result<(), String> {
    if host.is_empty()
        || host.len() > 253
        || host.starts_with('-')
        || host
            .chars()
            .any(|c| !c.is_ascii_alphanumeric() && !matches!(c, '.' | '-' | ':'))
    {
        return Err("请输入有效的域名或 IP 地址，不包含命令、路径或空格".into());
    }
    if host.contains(':') && host.parse::<IpAddr>().is_err() {
        return Err("无效的 IPv6 地址".into());
    }
    if !host.contains(':')
        && host.split('.').any(|label| {
            label.is_empty() || label.len() > 63 || label.starts_with('-') || label.ends_with('-')
        })
    {
        return Err("无效的域名".into());
    }
    Ok(())
}
pub fn http_url(value: &str) -> Result<reqwest::Url, String> {
    let url = reqwest::Url::parse(value).map_err(|_| "无效的 HTTP 地址")?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
    {
        return Err("只支持不含用户名密码的 HTTP/HTTPS 地址".into());
    }
    Ok(url)
}
pub async fn connections(p: Value) -> Reply {
    let filter = p["filter"].as_str().unwrap_or("");
    if filter.len() > 200 {
        return Err("筛选内容过长".into());
    }
    powershell(r#"$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new();
    $a=$env:SUNDAY_NETWORK_ARGS|ConvertFrom-Json; $processes=@{}; Get-Process|ForEach-Object {$processes[$_.Id]=$_};
    $rows=@(Get-NetTCPConnection -ErrorAction SilentlyContinue|ForEach-Object {$p=$processes[[int]$_.OwningProcess];
        [pscustomobject]@{protocol='TCP';local_address=$_.LocalAddress;local_port=$_.LocalPort;remote_address=$_.RemoteAddress;remote_port=$_.RemotePort;pid=$_.OwningProcess;process=$p.ProcessName;path=$p.Path;state=[string]$_.State}});
    $rows+=@(Get-NetUDPEndpoint -ErrorAction SilentlyContinue|ForEach-Object {$p=$processes[[int]$_.OwningProcess];
        [pscustomobject]@{protocol='UDP';local_address=$_.LocalAddress;local_port=$_.LocalPort;remote_address='';remote_port=0;pid=$_.OwningProcess;process=$p.ProcessName;path=$p.Path;state='Bound'}});
    if($a.filter){$rows=@($rows|Where-Object {($_|ConvertTo-Json -Compress).IndexOf([string]$a.filter,[StringComparison]::OrdinalIgnoreCase) -ge 0})};
    @{connections=@($rows|Select-Object -First 2000);total=$rows.Count;traffic_source='system_connections';per_process_bytes_available=$false}|ConvertTo-Json -Depth 5 -Compress"#,json!({"filter":filter})).await
}
pub async fn interfaces() -> Reply {
    powershell(r#"$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new();
    @{interfaces=@(Get-NetIPConfiguration|ForEach-Object {[pscustomobject]@{index=$_.InterfaceIndex;name=$_.InterfaceAlias;ipv4=@($_.IPv4Address.IPAddress);ipv6=@($_.IPv6Address.IPAddress);gateway=@($_.IPv4DefaultGateway.NextHop);dns=@($_.DNSServer.ServerAddresses)}});routes=@(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue|Select-Object InterfaceIndex,NextHop,RouteMetric)}|ConvertTo-Json -Depth 6 -Compress"#,json!({})).await
}
pub async fn lan() -> Reply {
    powershell(r#"$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new();
    @{devices=@(Get-NetNeighbor|Where-Object {$_.State -notin @('Unreachable','Incomplete') -and $_.IPAddress -notmatch '^(224\.|239\.|ff)'}|Select-Object IPAddress,LinkLayerAddress,InterfaceIndex,@{n='state';e={[string]$_.State}});source='neighbor_cache';note='已知邻居缓存；不表示所有设备当前在线'}|ConvertTo-Json -Depth 5 -Compress"#,json!({})).await
}
pub async fn dns_query(p: Value) -> Reply {
    let host = p["domain"].as_str().ok_or("请输入查询域名")?;
    validate_host(host)?;
    let provider = p["provider"].as_str().unwrap_or("system");
    let query_type = p["type"].as_str().unwrap_or("A");
    if !matches!(query_type, "A" | "AAAA" | "MX" | "TXT" | "CNAME") {
        return Err("不支持的 DNS 记录类型".into());
    }
    let start = Instant::now();
    if provider == "system" {
        if !matches!(query_type, "A" | "AAAA") {
            return powershell(r#"$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new();$a=$env:SUNDAY_NETWORK_ARGS|ConvertFrom-Json;@{provider='system';domain=$a.domain;answers=@(Resolve-DnsName -Name $a.domain -Type $a.type -DnsOnly|Select-Object Name,Type,TTL,IPAddress,NameHost,NameExchange,Strings);changes_system=$false}|ConvertTo-Json -Depth 5 -Compress"#,p).await;
        }
        let rows =
            tokio::time::timeout(Duration::from_secs(5), tokio::net::lookup_host((host, 443)))
                .await
                .map_err(|_| "系统 DNS 查询超时")?
                .map_err(|_| "系统 DNS 解析失败")?;
        let mut addresses = Vec::new();
        for row in rows.take(32) {
            if row.is_ipv4() != (query_type == "A") {
                continue;
            }
            let address = row.ip().to_string();
            if !addresses.contains(&address) {
                addresses.push(address);
            }
        }
        return Ok(
            json!({"provider":"system","domain":host,"addresses":addresses,"ms":start.elapsed().as_millis(),"changes_system":false}),
        );
    }
    let endpoint = match provider {
        "cloudflare" => "https://cloudflare-dns.com/dns-query",
        "google" => "https://dns.google/resolve",
        _ => return Err("请选择 system、cloudflare 或 google".into()),
    };
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build()
        .map_err(|_| "DNS 客户端初始化失败")?;
    let mut url = reqwest::Url::parse(endpoint).map_err(|_| "DoH 服务地址无效")?;
    url.query_pairs_mut()
        .append_pair("name", host)
        .append_pair("type", query_type);
    let mut response = client
        .get(url)
        .header("Accept", "application/dns-json")
        .send()
        .await
        .map_err(|_| "DoH 查询失败或证书验证失败")?
        .error_for_status()
        .map_err(|_| "DoH 服务返回错误")?;
    let mut bytes = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "DoH 响应读取失败")? {
        if bytes.len() + chunk.len() > 65536 {
            return Err("DoH 响应过大".into());
        }
        bytes.extend_from_slice(&chunk);
    }
    let answer: Value = serde_json::from_slice(&bytes).map_err(|_| "DoH 返回无效数据")?;
    Ok(
        json!({"provider":provider,"domain":host,"status":answer["Status"],"answers":answer["Answer"],"ms":start.elapsed().as_millis(),"changes_system":false}),
    )
}
pub fn match_rule(rules: &[Value], p: Value) -> Reply {
    let domain = p["domain"].as_str().ok_or("缺少域名")?.to_lowercase();
    validate_host(&domain)?;
    let matched = rules
        .iter()
        .filter(|r| {
            let pattern = r["domain"].as_str().unwrap_or("").to_lowercase();
            domain == pattern || domain.ends_with(&format!(".{pattern}"))
        })
        .max_by_key(|r| r["domain"].as_str().unwrap_or("").len());
    Ok(
        json!({"domain":domain,"matched":matched,"outbound":matched.map(|r|r["outbound"].clone()).unwrap_or(json!("DIRECT")),"applied_to_system":false}),
    )
}
impl Controller {
    pub async fn diagnose(&mut self, p: Value) -> Reply {
        let target = p["target"].as_str().unwrap_or("github.com");
        validate_host(target)?;
        let port = p["port"].as_u64().unwrap_or(443);
        if !(1..=65535).contains(&port) {
            return Err("端口应为 1–65535".into());
        }
        let started = Instant::now();
        let mut checks = Vec::new();
        let resolved = tokio::time::timeout(
            Duration::from_secs(5),
            tokio::net::lookup_host((target, port as u16)),
        )
        .await;
        let mut addresses = Vec::new();
        match resolved{Ok(Ok(rows))=>{for row in rows.take(12){if !addresses.contains(&row){addresses.push(row);}}checks.push(json!({"stage":"DNS","ok":!addresses.is_empty(),"addresses":addresses.iter().map(|a|a.ip().to_string()).collect::<Vec<_>>(),"ms":started.elapsed().as_millis()}));},_=>checks.push(json!({"stage":"DNS","ok":false,"evidence":"系统解析在 5 秒内未成功；不能仅凭此判定 DNS 污染"}))}
        let mut probes = tokio::task::JoinSet::new();
        for address in addresses {
            probes.spawn(async move{let time=Instant::now();let ok=matches!(tokio::time::timeout(Duration::from_secs(3),tokio::net::TcpStream::connect(address)).await,Ok(Ok(_)));json!({"stage":"TCP","address":address.to_string(),"ok":ok,"ms":time.elapsed().as_millis()})});
        }
        while let Some(probe) = probes.join_next().await {
            if let Ok(value) = probe {
                checks.push(value);
            }
        }
        let url = if target.contains(':') {
            format!("https://[{target}]:{port}/")
        } else {
            format!("https://{target}:{port}/")
        };
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(8))
            .redirect(reqwest::redirect::Policy::limited(5))
            .build()
            .map_err(|e| e.to_string())?;
        let time = Instant::now();
        match client.head(&url).send().await{Ok(response)=>checks.push(json!({"stage":"TLS / HTTP","ok":response.status().as_u16()<500,"status":response.status().as_u16(),"ms":time.elapsed().as_millis(),"evidence":"系统信任库校验后的 HTTPS HEAD；无内容解密"})),Err(error)=>checks.push(json!({"stage":"TLS / HTTP","ok":false,"evidence":if error.is_timeout(){"HTTPS 请求超时"}else if error.is_connect(){"HTTPS 连接或证书校验失败"}else{"HTTPS 请求失败"}}))}
        if matches!(p["kind"].as_str(), Some("ping" | "traceroute")) {
            let trace = p["kind"] == "traceroute";
            let mut command =
                tokio::process::Command::new(if trace { "tracert.exe" } else { "ping.exe" });
            if trace {
                command.args(["-d", "-h", "8", "-w", "500", target]);
            } else {
                command.args(["-n", "4", "-w", "1000", target]);
            }
            command.kill_on_drop(true);
            #[cfg(windows)]
            command.creation_flags(0x08000000);
            let result = tokio::time::timeout(Duration::from_secs(15), command.output()).await;
            checks.push(match result{Ok(Ok(out))=>json!({"stage":if trace{"Traceroute"}else{"Ping"},"ok":out.status.success(),"evidence":String::from_utf8_lossy(&out.stdout).chars().take(12000).collect::<String>()}),_=>json!({"stage":"ICMP","ok":false,"evidence":"探测超时或工具不可用；目标可能禁用 ICMP"})});
        }
        let failures = checks.iter().filter(|v| v["ok"] == false).count();
        let report = json!({"id":uuid::Uuid::new_v4().to_string(),"time":chrono::Utc::now().to_rfc3339(),"target":target,"checks":checks,"elapsed_ms":started.elapsed().as_millis(),"failures":failures,
            "confidence":"仅确认上列测量结果；未执行系统修改","recommendation":if failures==0{"当前检查通过，无需修复"}else{"按 DNS → TCP → TLS/HTTP 顺序检查失败项；尝试其他出口前先确认代理和防火墙状态"}});
        self.saved.reports.push(report.clone());
        while self.saved.reports.len() > 50 {
            self.saved.reports.remove(0);
        }
        self.event("diagnose", "完成网络诊断");
        self.persist()?;
        Ok(json!({"report":report}))
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_shell_injection() {
        for v in [
            "example.com; whoami",
            "-n 999",
            "$(whoami)",
            "https://a.com",
            "a\nb",
        ] {
            assert!(validate_host(v).is_err());
        }
        for v in ["github.com", "127.0.0.1", "::1"] {
            assert!(validate_host(v).is_ok());
        }
    }
    #[test]
    fn longest_domain_match_wins() {
        let rules = vec![
            json!({"domain":"example.com","outbound":"PROXY"}),
            json!({"domain":"safe.example.com","outbound":"DIRECT"}),
        ];
        assert_eq!(
            match_rule(&rules, json!({"domain":"safe.example.com"})).unwrap()["outbound"],
            "DIRECT"
        );
        assert_eq!(
            match_rule(&rules, json!({"domain":"fakeexample.com"})).unwrap()["outbound"],
            "DIRECT"
        );
    }
    #[test]
    fn rejects_download_credentials_and_non_http() {
        for url in [
            "file:///etc/passwd",
            "ftp://example.com/x",
            "https://user:secret@example.com/x",
        ] {
            assert!(http_url(url).is_err());
        }
    }
}
