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
// user:“检查本机网络接口、网关与局域网”+(只做真实探测：TCP 连接与系统解析，ICMP 不响应不作为失败依据)。
async fn tcp_probe(address: &str, millis: u64) -> bool {
    let Ok(parsed) = address.parse::<std::net::SocketAddr>() else {
        return false;
    };
    matches!(
        tokio::time::timeout(
            Duration::from_millis(millis),
            tokio::net::TcpStream::connect(parsed)
        )
        .await,
        Ok(Ok(_))
    )
}
// WinINET 的 ProxyServer 可能是 "http=127.0.0.1:7890;https=..." 或单个 host:port。
fn proxy_endpoint(server: &str) -> Option<String> {
    for part in server.split(';') {
        let value = part.rsplit('=').next().unwrap_or(part).trim();
        let value = value
            .trim_start_matches("http://")
            .trim_start_matches("https://")
            .trim_start_matches("socks5://");
        if let Some((host, port)) = value.rsplit_once(':') {
            if !host.is_empty() && port.parse::<u16>().map(|v| v > 0).unwrap_or(false) {
                return Some(format!("{host}:{port}"));
            }
        }
    }
    None
}
// 用 DoH 交叉验证：系统解析失败但 DoH 能解析，说明是本地 DNS 的问题，而不是断网。
async fn doh_resolves(host: &str) -> bool {
    let Ok(client) = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(5))
        .build()
    else {
        return false;
    };
    let Ok(mut url) = reqwest::Url::parse("https://cloudflare-dns.com/dns-query") else {
        return false;
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
        return false;
    };
    let Ok(answer) = response.json::<Value>().await else {
        return false;
    };
    answer["Answer"]
        .as_array()
        .map(|rows| !rows.is_empty())
        .unwrap_or(false)
}

impl Controller {
    // user:“提供一个普通用户可以理解的「检查网络」按钮”“诊断不依赖单一网站或单一服务端”+(本机/网关/DNS/外网/代理五层，全部来自真实测量)。
    async fn network_diagnose(&mut self) -> Reply {
        let started = Instant::now();
        let mut checks = Vec::new();
        let info = interfaces().await.unwrap_or_else(|_| json!({}));
        let adapters = info["interfaces"].as_array().cloned().unwrap_or_default();
        let active: Vec<(String, String, Vec<String>)> = adapters
            .iter()
            .filter_map(|row| {
                let name = row["name"].as_str()?.to_string();
                let ipv4 = row["ipv4"]
                    .as_array()
                    .map(|list| {
                        list.iter()
                            .filter_map(|v| v.as_str().map(str::to_string))
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let gateways = row["gateway"]
                    .as_array()
                    .map(|list| {
                        list.iter()
                            .filter_map(|v| v.as_str().map(str::to_string))
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                let primary = ipv4.first()?.clone();
                Some((name, primary, gateways))
            })
            .collect();
        let local_ok = !active.is_empty();
        checks.push(json!({"stage":"本机网络","ok":local_ok,"evidence":if local_ok {
            format!("{} 个网卡有地址：{}", active.len(), active.iter().map(|(name, ip, _)| format!("{name} {ip}")).collect::<Vec<_>>().join("、"))
        } else { "没有找到带 IPv4 地址的网卡".to_string() }}));

        let gateways: Vec<String> = active
            .iter()
            .flat_map(|(_, _, rows)| rows.clone())
            .collect();
        let mut gateway_ok = false;
        for gateway in &gateways {
            for port in [53u16, 80] {
                if tcp_probe(&format!("{gateway}:{port}"), 1200).await {
                    gateway_ok = true;
                }
            }
        }
        let neighbors = lan()
            .await
            .ok()
            .and_then(|value| value["devices"].as_array().map(|rows| rows.len()))
            .unwrap_or(0);
        checks.push(json!({"stage":"网关","ok":gateway_ok,"evidence":if gateways.is_empty() {
            "没有默认网关，可能只有本地连接".to_string()
        } else if gateway_ok {
            format!("{} 有响应；邻居缓存里有 {} 台设备", gateways.join("、"), neighbors)
        } else {
            format!("{} 在 1.2 秒内没有响应；邻居缓存里有 {} 台设备", gateways.join("、"), neighbors)
        }}));

        let mut system_ok = false;
        let mut resolved: Vec<String> = Vec::new();
        for host in ["www.example.com", "github.com"] {
            if let Ok(Ok(rows)) = tokio::time::timeout(
                Duration::from_secs(4),
                tokio::net::lookup_host((host, 443)),
            )
            .await
            {
                for row in rows.take(4) {
                    let address = row.ip().to_string();
                    if !resolved.contains(&address) {
                        resolved.push(address);
                    }
                    system_ok = true;
                }
            }
        }
        let doh_ok = doh_resolves("github.com").await;
        checks.push(json!({"stage":"DNS","ok":system_ok,"evidence":if system_ok {
            format!("系统解析成功：{}", resolved.iter().take(4).cloned().collect::<Vec<_>>().join("、"))
        } else if doh_ok {
            "系统解析失败，但 DoH 能解析出地址".to_string()
        } else {
            "系统解析与 DoH 都没有拿到地址".to_string()
        }}));

        let mut external_ok = false;
        let mut external: Vec<String> = Vec::new();
        for address in ["1.1.1.1:443", "223.5.5.5:443"] {
            let ok = tcp_probe(address, 2500).await;
            external.push(format!("{address} {}", if ok { "可达" } else { "不可达" }));
            if ok {
                external_ok = true;
            }
        }
        checks.push(json!({"stage":"外网连接","ok":external_ok,"evidence":external.join("；")}));

        let proxy = crate::system::inspect(json!({"kind":"proxy"}))
            .await
            .unwrap_or_else(|_| json!({}));
        let proxy_enabled =
            proxy["enabled"].as_u64() == Some(1) || proxy["enabled"].as_bool() == Some(true);
        let proxy_server = proxy["server"].as_str().unwrap_or("");
        let (proxy_ok, proxy_note) = if !proxy_enabled {
            (true, "系统代理未启用".to_string())
        } else if let Some(endpoint) = proxy_endpoint(proxy_server) {
            if tcp_probe(&endpoint, 1200).await {
                (true, format!("系统代理 {proxy_server} 可以连接"))
            } else {
                (false, format!("系统代理 {proxy_server} 没有程序在监听"))
            }
        } else {
            (
                false,
                format!("系统代理已启用，但地址无法识别：{proxy_server}"),
            )
        };
        checks.push(json!({"stage":"代理","ok":proxy_ok,"evidence":proxy_note}));

        let conclusion = if !local_ok {
            json!({"code":"no_interface","text":"这台电脑没有连上网络","suggestion":"检查 Wi-Fi 或网线，确认网卡没有被禁用"})
        } else if gateways.is_empty() {
            json!({"code":"no_gateway","text":"已经连上网络，但没有拿到网关","suggestion":"重新连接一次 Wi-Fi，或检查路由器是否分配地址"})
        } else if !gateway_ok {
            json!({"code":"gateway_unreachable","text":"能连上网络，但访问不到路由器","suggestion":"重启路由器或重新连接；如果是公共 Wi-Fi，先完成网页认证"})
        } else if !system_ok && doh_ok {
            json!({"code":"system_dns_failed","text":"系统 DNS 解析失败，网络本身是通的","suggestion":"可以把 DNS 换成 1.1.1.1 或 223.5.5.5；修改前会保存原设置"})
        } else if !system_ok {
            json!({"code":"dns_failed","text":"域名解析失败，其它网络看起来正常","suggestion":"先确认代理没有劫持 DNS，再尝试切换 DNS 服务器"})
        } else if !external_ok {
            json!({"code":"no_internet","text":"局域网正常，但访问不了外网","suggestion":"路由器可能没有连上运营商；校园网或公司网需要先认证"})
        } else if !proxy_ok {
            json!({"code":"proxy_broken","text":"网络正常，但系统代理不可用","suggestion":"关闭系统代理，或换一条可用线路后再试"})
        } else {
            json!({"code":"ok","text":"网络正常","suggestion":"本机、网关、域名解析、外网和代理检查都通过"})
        };
        let failures = checks.iter().filter(|row| row["ok"] == false).count();
        let report = json!({
            "id":uuid::Uuid::new_v4().to_string(),
            "time":chrono::Utc::now().to_rfc3339(),
            "kind":"network",
            "target":"network",
            "checks":checks,
            "elapsed_ms":started.elapsed().as_millis(),
            "failures":failures,
            "confidence":"仅确认上列测量结果；未执行系统修改",
            "conclusion":conclusion,
        });
        self.saved.reports.push(report.clone());
        while self.saved.reports.len() > 50 {
            self.saved.reports.remove(0);
        }
        self.event("diagnose", "完成网络检查");
        self.persist()?;
        Ok(json!({"report":report}))
    }
    pub async fn diagnose(&mut self, p: Value) -> Reply {
        if p["kind"].as_str() == Some("network") {
            return self.network_diagnose().await;
        }
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
        // user:“网络正常，但目标网站无响应”“DNS 解析失败，可尝试切换 DNS”+(按失败所在层给结论，而不是一句通用建议)。
        let dns_failed = checks.iter().any(|v| v["stage"] == "DNS" && v["ok"] == false);
        let tcp_failed = checks.iter().any(|v| v["stage"] == "TCP" && v["ok"] == false);
        let tls_failed = checks.iter().any(|v| v["stage"] == "TLS / HTTP" && v["ok"] == false);
        let server_error = checks
            .iter()
            .any(|v| v["stage"] == "TLS / HTTP" && v["status"].as_u64().map(|code| code >= 500).unwrap_or(false));
        let (code, text, suggestion) = if failures == 0 {
            ("ok", "这个网站可以正常访问", "本次检查的地址解析、连接和响应都通过")
        } else if dns_failed {
            ("dns_failed", "找不到这个网站的地址", "域名解析失败，可尝试切换 DNS 服务器；如果其它网站正常，也可能只是这一个域名")
        } else if tcp_failed {
            ("tcp_failed", "能解析地址，但连不上对方的端口", "网络本身可能是通的，但目标端口被阻断或服务没开；先换一条线路再试")
        } else if server_error {
            ("server_error", "网络正常，但这个网站自己返回了错误", "对方服务返回 5xx，问题在网站一侧，稍后再试")
        } else if tls_failed {
            ("tls_failed", "连接建立失败，或证书校验没有通过", "可能是中间人劫持、代理拦截或系统时间不对；先确认代理状态")
        } else {
            ("unknown", "检查没有全部通过", "按 地址解析 → 连接 → 响应 的顺序看失败项")
        };
        let report = json!({"id":uuid::Uuid::new_v4().to_string(),"time":chrono::Utc::now().to_rfc3339(),"kind":"site","target":target,"checks":checks,"elapsed_ms":started.elapsed().as_millis(),"failures":failures,
            "confidence":"仅确认上列测量结果；未执行系统修改",
            "conclusion":{"code":code,"text":text,"suggestion":suggestion},
            "recommendation":suggestion});
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
    fn proxy_server_forms_are_parsed() {
        // user:“系统代理读取、检测、冲突识别”+(WinINET 的多种写法都要能取到 host:port)。
        assert_eq!(proxy_endpoint("127.0.0.1:17890").as_deref(), Some("127.0.0.1:17890"));
        assert_eq!(
            proxy_endpoint("http=127.0.0.1:7890;https=127.0.0.1:7890").as_deref(),
            Some("127.0.0.1:7890")
        );
        assert_eq!(proxy_endpoint("http://127.0.0.1:8080").as_deref(), Some("127.0.0.1:8080"));
        assert_eq!(proxy_endpoint(""), None);
        assert_eq!(proxy_endpoint("no-port"), None);
    }
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
