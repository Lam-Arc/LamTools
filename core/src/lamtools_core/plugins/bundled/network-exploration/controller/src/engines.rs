// user:“实现这个插件，也正好实验我们的新插件架构”+(可选内核只监听本机，使用随机口令和受控子进程，不接管系统网络)。
use crate::{
    observe::http_url,
    state::{Controller, Reply},
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    path::PathBuf,
    time::{Duration, Instant},
};
use tokio::process::{Child, Command};

const BUILTIN_TARGETS: [&str; 6] = [
    "DIRECT",
    "REJECT",
    "REJECT-DROP",
    "PASS",
    "COMPATIBLE",
    "GLOBAL",
];

pub struct Engines {
    data: PathBuf,
    pub proxy: Option<Child>,
    pub aria: Option<Child>,
    proxy_port: u16,
    aria_port: u16,
    secret: String,
    client: reqwest::Client,
    proxy_started: Option<chrono::DateTime<chrono::Utc>>,
}
fn free_port() -> Result<u16, String> {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    Ok(listener.local_addr().map_err(|e| e.to_string())?.port())
}
fn command(path: PathBuf) -> Command {
    let mut c = Command::new(path);
    c.kill_on_drop(true)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    c.creation_flags(0x08000000);
    c
}
async fn terminate(child: &mut Option<Child>) {
    if let Some(mut process) = child.take() {
        let _ = process.kill().await;
        let _ = process.wait().await;
    }
}
fn selector_members(proxies: &Value, group: &str) -> Result<Vec<String>, String> {
    let entry = proxies
        .get(group)
        .ok_or_else(|| format!("找不到线路分组 {group}"))?;
    if entry["type"].as_str() != Some("Selector") {
        return Err("只有手动选择分组可以自动选线".into());
    }
    let members = entry["all"].as_array().ok_or("该分组没有可选线路")?;
    let mut names = Vec::new();
    for member in members {
        let Some(name) = member.as_str() else {
            continue;
        };
        if name.is_empty()
            || BUILTIN_TARGETS
                .iter()
                .any(|builtin| builtin.eq_ignore_ascii_case(name))
            || names.iter().any(|existing| existing == name)
        {
            continue;
        }
        names.push(name.to_string());
    }
    if names.is_empty() {
        return Err("该分组没有可测速线路".into());
    }
    Ok(names)
}
fn default_selector_group(proxies: &Value) -> Result<String, String> {
    let map = proxies.as_object().ok_or("代理节点数据无效")?;
    for (name, entry) in map {
        if entry["type"].as_str() == Some("Selector") && selector_members(proxies, name).is_ok() {
            return Ok(name.clone());
        }
    }
    Err("没有可自动选线的分组".into())
}
fn rank_candidates(mut rows: Vec<Value>) -> Vec<Value> {
    rows.sort_by(|a, b| {
        let left = a["delay"].as_u64().filter(|value| *value > 0).unwrap_or(u64::MAX);
        let right = b["delay"].as_u64().filter(|value| *value > 0).unwrap_or(u64::MAX);
        left.cmp(&right).then_with(|| {
            a["name"]
                .as_str()
                .unwrap_or("")
                .cmp(b["name"].as_str().unwrap_or(""))
        })
    });
    rows
}
fn pick_fastest(rows: &[Value]) -> Option<(String, u64)> {
    rows.iter().find_map(|row| {
        Some((
            row["name"].as_str()?.to_string(),
            row["delay"].as_u64().filter(|value| *value > 0)?,
        ))
    })
}
async fn delay_probe(
    client: reqwest::Client,
    port: u16,
    secret: String,
    name: String,
    target: String,
) -> Value {
    let started = Instant::now();
    let mut url = match reqwest::Url::parse(&format!("http://127.0.0.1:{port}/proxies")) {
        Ok(url) => url,
        Err(_) => return json!({"name":name,"error":"测速地址无效"}),
    };
    url.path_segments_mut()
        .map(|mut segments| {
            segments.push(&name).push("delay");
        })
        .ok();
    url.query_pairs_mut()
        .append_pair("timeout", "4000")
        .append_pair("url", &target);
    match client.get(url).bearer_auth(secret).send().await {
        Ok(response) if response.status().is_success() => {
            let value: Value = response.json().await.unwrap_or_default();
            match value["delay"].as_u64().filter(|delay| *delay > 0) {
                Some(delay) => json!({"name":name,"delay":delay,"ms":started.elapsed().as_millis() as u64}),
                None => json!({"name":name,"error":"测速未返回延迟"}),
            }
        }
        Ok(response) => json!({"name":name,"error":format!("节点返回 {}",response.status().as_u16())}),
        Err(_) => json!({"name":name,"error":"测速请求失败或超时"}),
    }
}
pub async fn protect(text: &str) -> Result<String, String> {
    crate::credentials::protect(text)
}
pub async fn unprotect(text: &str) -> Result<String, String> {
    crate::credentials::unprotect(text)
}
impl Engines {
    pub fn new(data: PathBuf) -> Result<Self, String> {
        Ok(Self {
            data,
            proxy: None,
            aria: None,
            proxy_port: 0,
            aria_port: 0,
            secret: format!(
                "{}{}",
                uuid::Uuid::new_v4().simple(),
                uuid::Uuid::new_v4().simple()
            ),
            client: reqwest::Client::builder()
                .no_proxy()
                .timeout(Duration::from_secs(8))
                .build()
                .map_err(|e| e.to_string())?,
            proxy_started: None,
        })
    }
    pub fn available(&self) -> Value {
        json!({"mihomo":self.data.join("engines/mihomo.exe").is_file(),"aria2":self.data.join("engines/aria2c.exe").is_file()})
    }
    fn binary(&self, name: &str) -> Result<PathBuf, String> {
        let path = self.data.join("engines").join(format!("{name}.exe"));
        let receipt: Value = serde_json::from_slice(
            &std::fs::read(
                self.data
                    .join("engines")
                    .join(format!("{name}.receipt.json")),
            )
            .map_err(|_| format!("请先安装 {name} 内核"))?,
        )
        .map_err(|_| "内核校验凭据损坏")?;
        let digest = format!(
            "{:x}",
            Sha256::digest(std::fs::read(&path).map_err(|_| "内核文件不存在")?)
        );
        if receipt["binary_sha256"] != digest {
            return Err("内核文件校验失败，请重新安装".into());
        }
        Ok(path)
    }
    pub async fn proxy_status(&mut self) -> Value {
        let config_saved = self.data.join("proxy.config.secure").is_file();
        let running = self
            .proxy
            .as_mut()
            .map(|p| p.try_wait().ok().flatten().is_none())
            .unwrap_or(false);
        if !running {
            self.proxy = None;
            self.proxy_started = None;
            return json!({"running":false,"mode":"direct","traffic_source":"mihomo_only","config_saved":config_saved});
        }
        // user:“样式示例：不必照抄，只是方向”+(首页显示真实连接时长，控制器只报告启动时刻)。
        let started = self
            .proxy_started
            .map(|value| value.to_rfc3339())
            .unwrap_or_default();
        match self.proxy_request("GET", "/traffic", None).await {
            Ok(traffic) => {
                json!({"running":true,"traffic":traffic,"traffic_source":"mihomo_only","controller":"127.0.0.1","mode":"managed","started_at":started,"config_saved":config_saved})
            }
            Err(_) => json!({"running":true,"healthy":false,"traffic_source":"mihomo_only","started_at":started,"config_saved":config_saved}),
        }
    }
    async fn proxy_request(&self, method: &str, path: &str, body: Option<Value>) -> Reply {
        let url = format!("http://127.0.0.1:{}{path}", self.proxy_port);
        let mut request = self
            .client
            .request(method.parse().map_err(|_| "HTTP method")?, url)
            .bearer_auth(&self.secret);
        if let Some(value) = body {
            request = request.json(&value);
        }
        let response = request.send().await.map_err(|_| "Mihomo 控制接口不可用")?;
        if !response.status().is_success() {
            return Err(format!("Mihomo 返回 {}", response.status().as_u16()));
        }
        if response.status().as_u16() == 204 {
            return Ok(json!({"ok":true}));
        }
        let mut response = response;
        let mut bytes = Vec::new();
        while let Some(chunk) = response.chunk().await.map_err(|_| "Mihomo 响应读取失败")? {
            if bytes.len() + chunk.len() > 2 * 1024 * 1024 {
                return Err("Mihomo 响应过大，请筛选连接".into());
            }
            bytes.extend_from_slice(&chunk);
            // /traffic is a newline-delimited stream, not a finite JSON body.
            if path == "/traffic" {
                if let Some(end) = bytes.iter().position(|c| *c == b'\n') {
                    bytes.truncate(end);
                    break;
                }
            }
        }
        serde_json::from_slice(&bytes).map_err(|_| "Mihomo 返回无效数据".into())
    }
    pub async fn proxy_config(&mut self, p: Value) -> Reply {
        if self.proxy.is_some() {
            return Err("请先停止代理再导入配置".into());
        }
        let mut content = p["content"].as_str().unwrap_or("").to_string();
        if let Some(source) = p["subscription"].as_str() {
            let url = http_url(source)?;
            if url.scheme() != "https" {
                return Err("订阅必须使用 HTTPS".into());
            }
            // user:“https://sub.serverpulse.me/clash.yaml一直正在处理，始终没有添加”+(订阅主机直连很慢，优先借系统现有代理下载，并给足超时)。
            let (client, used_proxy) = subscription_client().await;
            let response = match client.get(url.clone()).send().await {
                Ok(response) => response,
                Err(_error) if used_proxy => {
                    let direct = reqwest::Client::builder()
                        .no_proxy()
                        .timeout(Duration::from_secs(25))
                        .build()
                        .map_err(|_| "订阅客户端初始化失败")?;
                    direct
                        .get(url)
                        .send()
                        .await
                        .map_err(|error| subscription_error(&error))?
                }
                Err(error) => return Err(subscription_error(&error)),
            };
            let response = response
                .error_for_status()
                .map_err(|_| "订阅服务返回错误")?;
            if response.content_length().unwrap_or(0) > 2 * 1024 * 1024 {
                return Err("订阅过大".into());
            }
            let mut response = response;
            let mut bytes = Vec::new();
            while let Some(chunk) = response
                .chunk()
                .await
                .map_err(|error| subscription_error(&error))?
            {
                if bytes.len() + chunk.len() > 2 * 1024 * 1024 {
                    return Err("订阅过大".into());
                }
                bytes.extend_from_slice(&chunk);
            }
            content = String::from_utf8(bytes).map_err(|_| "订阅不是 UTF-8 YAML")?;
        }
        sanitize_config(&content, 12345, &self.secret)?;
        let cipher = protect(&content).await?;
        let temporary = self.data.join("proxy.config.next");
        tokio::fs::write(&temporary, cipher)
            .await
            .map_err(|e| e.to_string())?;
        tokio::fs::rename(temporary, self.data.join("proxy.config.secure"))
            .await
            .map_err(|e| e.to_string())?;
        Ok(
            json!({"saved":true,"credentials":"Windows DPAPI 当前用户加密","tun":false,"system_proxy":false}),
        )
    }
    pub async fn start_proxy(&mut self, _p: Value) -> Reply {
        if let Some(process) = self.proxy.as_mut() {
            if process
                .try_wait()
                .map_err(|_| "无法检查 Mihomo 状态")?
                .is_none()
            {
                return Ok(self.proxy_status().await);
            }
            self.proxy = None;
        }
        let binary = self.binary("mihomo")?;
        let mixed_listener = std::net::TcpListener::bind("127.0.0.1:17890")
            .map_err(|_| "代理端口 17890 已被占用，请先停止占用该端口的程序")?;
        drop(mixed_listener);
        let path = self.data.join("runtime");
        tokio::fs::create_dir_all(&path)
            .await
            .map_err(|e| e.to_string())?;
        let cipher = tokio::fs::read_to_string(self.data.join("proxy.config.secure"))
            .await
            .map_err(|_| "请先导入 Mihomo YAML 或订阅")?;
        self.proxy_port = free_port()?;
        let raw = unprotect(&cipher).await?;
        let config = sanitize_config(&raw, self.proxy_port, &self.secret)?;
        let mut config: serde_yaml::Value =
            serde_yaml::from_str(&config).map_err(|_| "配置无法解析")?;
        apply_common_acceleration(&mut config)?;
        let config = serde_yaml::to_string(&config).map_err(|_| "配置无法序列化")?;
        tokio::fs::write(path.join("mihomo.yaml"), config)
            .await
            .map_err(|e| e.to_string())?;
        self.proxy = Some(
            command(binary)
                .arg("-d")
                .arg(&path)
                .arg("-f")
                .arg(path.join("mihomo.yaml"))
                .spawn()
                .map_err(|_| "无法启动 Mihomo")?,
        );
        for _ in 0..50 {
            if self.proxy_request("GET", "/version", None).await.is_ok() {
                self.proxy_started = Some(chrono::Utc::now());
                return Ok(
                    json!({"running":true,"mixed_port":17890,"tun":false,"system_proxy":false}),
                );
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        self.stop_proxy().await?;
        Err("Mihomo 启动失败：检查端口、配置或规则资源".into())
    }
    pub async fn stop_proxy(&mut self) -> Reply {
        terminate(&mut self.proxy).await;
        self.proxy_started = None;
        let _ = tokio::fs::remove_file(self.data.join("runtime/mihomo.yaml")).await;
        Ok(json!({"running":false}))
    }
    pub async fn proxy_inspect(&self) -> Reply {
        let proxies = self.proxy_request("GET", "/proxies", None).await?;
        let rules = self.proxy_request("GET", "/rules", None).await?;
        let configs = self.proxy_request("GET", "/configs", None).await?;
        Ok(
            json!({"proxies":proxies["proxies"],"rules":rules["rules"],"mode":configs["mode"],"mixed_port":configs["mixed-port"]}),
        )
    }
    pub async fn proxy_select(&self, p: Value) -> Reply {
        let group = p["group"].as_str().ok_or("缺少代理组")?;
        let name = p["name"].as_str().ok_or("缺少节点名称")?;
        let mut url = reqwest::Url::parse("http://localhost/proxies").unwrap();
        url.path_segments_mut().unwrap().push(group);
        self.proxy_request("PUT", url.path(), Some(json!({"name":name})))
            .await
    }
    pub async fn proxy_delay(&self, p: Value) -> Reply {
        let name = p["name"].as_str().ok_or("缺少节点名称")?;
        let mut url = reqwest::Url::parse("http://localhost/proxies").unwrap();
        url.path_segments_mut().unwrap().push(name).push("delay");
        let target = p["url"]
            .as_str()
            .unwrap_or("https://www.gstatic.com/generate_204");
        http_url(target)?;
        url.query_pairs_mut()
            .append_pair("timeout", "5000")
            .append_pair("url", target);
        self.proxy_request(
            "GET",
            &format!("{}?{}", url.path(), url.query().unwrap()),
            None,
        )
        .await
    }
    // user:“继续进行网络工具插件的开发”+(一次点击测完分组内真实节点并切到最快可达线路，失败节点保留证据且不切换)。
    pub async fn proxy_optimize(&self, p: Value) -> Reply {
        let proxies = self.proxy_request("GET", "/proxies", None).await?["proxies"].clone();
        let group = match p["group"].as_str() {
            Some(value) if !value.is_empty() => value.to_string(),
            _ => default_selector_group(&proxies)?,
        };
        let members = selector_members(&proxies, &group)?;
        let target = p["url"]
            .as_str()
            .unwrap_or("https://www.gstatic.com/generate_204");
        http_url(target)?;
        let limit = p["limit"].as_u64().unwrap_or(64).clamp(1, 128) as usize;
        let select = p["select"].as_bool().unwrap_or(true);
        let mut queue = members.into_iter().take(limit);
        let mut tasks = tokio::task::JoinSet::new();
        for _ in 0..12 {
            if let Some(name) = queue.next() {
                tasks.spawn(delay_probe(
                    self.client.clone(),
                    self.proxy_port,
                    self.secret.clone(),
                    name,
                    target.to_string(),
                ));
            }
        }
        let mut rows = Vec::new();
        while let Some(result) = tasks.join_next().await {
            if let Ok(row) = result {
                rows.push(row);
            }
            if let Some(name) = queue.next() {
                tasks.spawn(delay_probe(
                    self.client.clone(),
                    self.proxy_port,
                    self.secret.clone(),
                    name,
                    target.to_string(),
                ));
            }
        }
        let rows = rank_candidates(rows);
        let fastest = pick_fastest(&rows);
        let mut selected = Value::Null;
        if let Some((name, _)) = fastest.clone() {
            if select {
                self.proxy_select(json!({"group":group,"name":name})).await?;
                selected = json!(name);
            }
        }
        Ok(json!({
            "group":group,
            "selected":selected,
            "fastest":fastest.as_ref().map(|(name,_)|name.clone()),
            "delay":fastest.map(|(_,delay)|delay),
            "tested":rows.len(),
            "candidates":rows,
            "changes_system":false,
            "note":if selected.is_null(){"没有可达线路，已保留当前选择"}else{"只在所选分组内切换节点，未修改系统设置"}
        }))
    }
    pub async fn proxy_mode(&self, p: Value) -> Reply {
        let mode = p["mode"].as_str().ok_or("缺少模式")?;
        if !matches!(mode, "direct" | "rule" | "global") {
            return Err("无效的代理模式".into());
        }
        self.proxy_request("PATCH", "/configs", Some(json!({"mode":mode})))
            .await
    }
    pub async fn aria_rpc(&self, method: &str, params: Vec<Value>) -> Reply {
        let mut args = vec![json!(format!("token:{}", self.secret))];
        args.extend(params);
        let response=self.client.post(format!("http://127.0.0.1:{}/jsonrpc",self.aria_port)).json(&json!({"jsonrpc":"2.0","id":"sunday","method":format!("aria2.{method}"),"params":args})).send().await.map_err(|_|"aria2 控制接口不可用")?;
        let value: Value = response.json().await.map_err(|_| "aria2 返回无效数据")?;
        if value.get("error").is_some() {
            return Err("aria2 操作失败，请检查任务状态、文件权限或链接有效期".into());
        }
        Ok(value["result"].clone())
    }
    async fn start_aria(&mut self) -> Result<(), String> {
        if let Some(process) = self.aria.as_mut() {
            if process.try_wait().map_err(|e| e.to_string())?.is_none() {
                return Ok(());
            }
        }
        self.aria_port = free_port()?;
        let binary = self.binary("aria2c")?;
        self.aria = Some(
            command(binary)
                .args([
                    "--enable-rpc=true",
                    "--rpc-listen-all=false",
                    "--rpc-allow-origin-all=false",
                    "--enable-dht=false",
                    "--enable-peer-exchange=false",
                    "--bt-enable-lpd=false",
                    "--disable-ipv6=false",
                    "--auto-file-renaming=false",
                    "--allow-overwrite=false",
                    "--continue=true",
                    "--max-tries=5",
                    "--retry-wait=3",
                    "--max-concurrent-downloads=3",
                    "--check-certificate=true",
                    "--console-log-level=error",
                    "--summary-interval=0",
                ])
                .arg(format!("--rpc-listen-port={}", self.aria_port))
                .arg(format!("--rpc-secret={}", self.secret))
                .spawn()
                .map_err(|_| "无法启动 aria2")?,
        );
        for _ in 0..30 {
            if self.aria_rpc("getVersion", vec![]).await.is_ok() {
                return Ok(());
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
        terminate(&mut self.aria).await;
        Err("aria2 启动失败".into())
    }
    pub async fn downloads(&mut self) -> Reply {
        if self.aria.is_none() {
            return Ok(json!({"tasks":[],"running":false}));
        }
        let keys = json!([
            "gid",
            "status",
            "totalLength",
            "completedLength",
            "downloadSpeed",
            "uploadSpeed",
            "connections",
            "errorCode"
        ]);
        let mut rows = Vec::new();
        for (method, mut args) in [
            ("tellActive", vec![]),
            ("tellWaiting", vec![json!(0), json!(1000)]),
            ("tellStopped", vec![json!(0), json!(1000)]),
        ] {
            args.push(keys.clone());
            let value = self.aria_rpc(method, args).await?;
            if let Some(items) = value.as_array() {
                rows.extend(items.clone());
            }
        }
        Ok(json!({"tasks":rows,"running":true}))
    }
    pub async fn download_action(&mut self, p: Value) -> Reply {
        let gid = p["gid"].as_str().ok_or("缺少任务 ID")?;
        if gid.len() != 16 || !gid.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err("任务 ID 无效".into());
        }
        let method = match p["action"].as_str() {
            Some("pause") => "pause",
            Some("resume") => "unpause",
            Some("cancel") => "remove",
            Some("first") => "changePosition",
            Some("limit") => "changeOption",
            _ => return Err("无效的任务操作".into()),
        };
        let mut args = vec![json!(gid)];
        if method == "changePosition" {
            args.extend([json!(0), json!("POS_SET")]);
        }
        if method == "changeOption" {
            let limit = p["bytes_per_second"].as_u64().ok_or("限速应为非负整数")?;
            args.push(json!({"max-download-limit":limit.to_string()}));
        }
        self.aria_rpc(method, args).await
    }
    pub async fn shutdown(&mut self) {
        let _ = self.stop_proxy().await;
        if self.aria.is_some() {
            let _ = self.aria_rpc("pauseAll", vec![]).await;
            let _ = self.aria_rpc("shutdown", vec![]).await;
            if let Some(process) = self.aria.as_mut() {
                let _ = tokio::time::timeout(Duration::from_secs(4), process.wait()).await;
            }
        }
        terminate(&mut self.aria).await;
    }
}

// user:“点一下‘一键加速’，然后就把 GitHub等常用的那些网站全部都加速了”+(内置常用站点规则，启动代理时排在最前面，不需要用户自己写规则)。
const COMMON_ACCELERATION: &[&[&str]] = &[
    &["github.com", "github.dev", "api.github.com", "github.githubassets.com", "githubusercontent.com", "githubapp.com", "github.io", "education.github.com", "resources.github.com", "uploads.github.com", "archivalprogram.github.com", "hub.docker.com", "greasyfork.org"],
    &["steamcommunity.com", "store.steampowered.com", "steamstatic.com", "steamcdn-a.akamaihd.net", "media.steampowered.com"],
    &["twitch.tv", "irc-ws.chat.twitch.tv", "passport.twitch.tv", "assets.twitch.tv", "clips-media-assets2.twitch.tv", "id.twitch.tv", "pubsub-edge.twitch.tv", "panels.twitch.tv", "supervisor-ext.twitch.tv"],
    &["spotify.com", "open.spotify.com"],
    &["google.com", "www.google.com", "translate.google.cn", "translate.googleapis.com", "fonts.gstatic.com", "fonts.googleapis.com", "themes.googleusercontent.com", "ajax.googleapis.com"],
    &["huggingface.co"],
    &["dropbox.com", "dl.dropboxusercontent.com", "mega.co.nz", "mega.io", "mega.nz", "onedrive.live.com", "storage.live.com"],
    &["nexusmods.com", "mod.io", "binarylage.mod.io", "files.nexus-cdn.com", "fandom.com", "pinterest.com", "artstation.com", "imgur.com", "vercel.app"],
];
// user:“本机加速层 你学习一下呗…它该抄就抄”+(照 FastGithub/Watt Toolkit 的域名匹配方式：精确域名或子域名)。
pub fn is_common_acceleration_host(host: &str) -> bool {
    let host = host.trim().trim_end_matches('.').to_ascii_lowercase();
    if host.is_empty() {
        return false;
    }
    COMMON_ACCELERATION
        .iter()
        .flat_map(|domains| domains.iter())
        .any(|domain| {
            host == *domain
                || (host.len() > domain.len()
                    && host.ends_with(domain)
                    && host.as_bytes()[host.len() - domain.len() - 1] == b'.')
        })
}
fn acceleration_target(config: &serde_yaml::Value) -> Option<String> {
    let usable = |name: &str| {
        !name.is_empty()
            && !name.contains(',')
            && !name.contains('\n')
            && !matches!(name, "DIRECT" | "REJECT" | "REJECT-DROP")
    };
    if let Some(groups) = config
        .get("proxy-groups")
        .and_then(serde_yaml::Value::as_sequence)
    {
        for group in groups {
            let Some(name) = group.get("name").and_then(serde_yaml::Value::as_str) else {
                continue;
            };
            let kind = group
                .get("type")
                .and_then(serde_yaml::Value::as_str)
                .unwrap_or("");
            if matches!(kind, "select" | "url-test" | "fallback" | "load-balance" | "relay")
                && usable(name)
            {
                return Some(name.to_string());
            }
        }
        if let Some(name) = groups
            .iter()
            .filter_map(|group| group.get("name").and_then(serde_yaml::Value::as_str))
            .find(|name| usable(name))
        {
            return Some(name.to_string());
        }
    }
    config
        .get("proxies")
        .and_then(serde_yaml::Value::as_sequence)
        .and_then(|proxies| proxies.first())
        .and_then(|proxy| proxy.get("name"))
        .and_then(serde_yaml::Value::as_str)
        .filter(|name| usable(name))
        .map(str::to_string)
}
fn apply_common_acceleration(config: &mut serde_yaml::Value) -> Result<(), String> {
    let Some(target) = acceleration_target(config) else {
        return Ok(());
    };
    let preset: Vec<String> = COMMON_ACCELERATION
        .iter()
        .flat_map(|domains| domains.iter())
        .map(|domain| format!("DOMAIN-SUFFIX,{domain},{target}"))
        .collect();
    match config
        .get_mut("rules")
        .and_then(serde_yaml::Value::as_sequence_mut)
    {
        Some(rules) => {
            let existing: std::collections::HashSet<String> = rules
                .iter()
                .filter_map(serde_yaml::Value::as_str)
                .map(str::to_string)
                .collect();
            for rule in preset.into_iter().rev() {
                if !existing.contains(&rule) {
                    rules.insert(0, serde_yaml::Value::String(rule));
                }
            }
        }
        None => {
            config["rules"] = serde_yaml::Value::Sequence(
                preset
                    .into_iter()
                    .map(serde_yaml::Value::String)
                    .collect(),
            );
        }
    }
    Ok(())
}

fn subscription_proxy(server: &str) -> Option<String> {
    let parts: Vec<&str> = server
        .split(';')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .collect();
    let candidate = parts
        .iter()
        .find_map(|part| part.strip_prefix("https="))
        .or_else(|| parts.iter().find_map(|part| part.strip_prefix("http=")))
        .or_else(|| {
            if parts.len() == 1 && !parts[0].contains('=') {
                Some(parts[0])
            } else {
                None
            }
        })?
        .trim();
    if candidate.is_empty()
        || candidate == "127.0.0.1:17890"
        || candidate == "localhost:17890"
    {
        return None;
    }
    Some(candidate.to_string())
}
async fn subscription_client() -> (reqwest::Client, bool) {
    let proxied = match crate::system::inspect(json!({"kind":"proxy"})).await {
        Ok(value) if value["enabled"].as_i64() == Some(1) => {
            value["server"].as_str().and_then(subscription_proxy)
        }
        _ => None,
    };
    if let Some(candidate) = proxied {
        let url = if candidate.contains("://") {
            candidate
        } else {
            format!("http://{candidate}")
        };
        if let Ok(proxy) = reqwest::Proxy::all(&url) {
            if let Ok(client) = reqwest::Client::builder()
                .proxy(proxy)
                .timeout(Duration::from_secs(55))
                .build()
            {
                return (client, true);
            }
        }
    }
    let client = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(75))
        .build()
        .unwrap_or_else(|_| reqwest::Client::new());
    (client, false)
}
fn subscription_error(error: &reqwest::Error) -> String {
    if error.is_timeout() {
        "订阅下载超时。可先在系统代理里连接一个可用节点，再回来重试".into()
    } else if error.is_connect() {
        "订阅连接失败，请检查地址或网络".into()
    } else {
        "订阅下载失败".into()
    }
}

fn sanitize_config(raw: &str, port: u16, secret: &str) -> Result<String, String> {
    if raw.len() > 2 * 1024 * 1024 {
        return Err("配置文件超过 2 MB".into());
    }
    let mut value: Value = serde_yaml::from_str(raw).map_err(|_| "配置必须是有效的 Mihomo YAML")?;
    let object = value.as_object_mut().ok_or("Mihomo 配置必须是对象")?;
    for key in [
        "external-ui",
        "external-ui-url",
        "external-ui-name",
        "external-controller-tls",
        "external-controller-unix",
        "external-controller-pipe",
        "script",
        "listeners",
    ] {
        object.remove(key);
    }
    for key in ["proxy-providers", "rule-providers"] {
        if let Some(providers) = object.get_mut(key) {
            let providers = providers.as_object_mut().ok_or("提供器必须是对象")?;
            for (name, provider) in providers {
                if name.len() > 100 {
                    return Err("提供器名称过长".into());
                }
                let entry = provider.as_object_mut().ok_or("提供器配置必须是对象")?;
                if entry.get("type").and_then(|v| v.as_str()) != Some("http") {
                    return Err("提供器仅允许经过 HTTPS 下载，不能读取本地文件".into());
                }
                let source = entry
                    .get("url")
                    .and_then(|v| v.as_str())
                    .ok_or("提供器缺少地址")?;
                let url = http_url(source)?;
                if url.scheme() != "https" {
                    return Err("提供器必须使用 HTTPS".into());
                }
                let hash = format!("{:x}", Sha256::digest(name.as_bytes()));
                entry.insert(
                    "path".into(),
                    json!(format!("./providers/{key}-{hash}.yaml")),
                );
            }
        }
    }
    object.insert(
        "external-controller".into(),
        json!(format!("127.0.0.1:{port}")),
    );
    object.insert("secret".into(), json!(secret));
    object.insert("allow-lan".into(), json!(false));
    object.insert("bind-address".into(), json!("127.0.0.1"));
    object.insert("mixed-port".into(), json!(17890));
    object.insert("port".into(), json!(0));
    object.insert("socks-port".into(), json!(0));
    object.insert("redir-port".into(), json!(0));
    object.insert("tproxy-port".into(), json!(0));
    object.insert("tun".into(), json!({"enable":false}));
    object.insert("dns".into(), json!({"enable":false}));
    object.insert("log-level".into(), json!("silent"));
    serde_yaml::to_string(&value).map_err(|_| "配置生成失败".into())
}

impl Controller {
    pub async fn add_download(&mut self, p: Value) -> Reply {
        let url = p["url"].as_str().ok_or("缺少下载地址")?;
        let parsed = http_url(url)?;
        let name = p["filename"]
            .as_str()
            .filter(|s| !s.is_empty())
            .unwrap_or("download.bin");
        if name.len() > 200
            || name.contains(['/', '\\', ':', '\0', '<', '>', '"', '|', '?', '*'])
            || name.chars().any(|c| c.is_control())
            || name == "."
            || name == ".."
            || name.ends_with(['.', ' '])
        {
            return Err("请输入不含路径的文件名".into());
        }
        let connections = p["connections"].as_u64().unwrap_or(8);
        if !(1..=16).contains(&connections) {
            return Err("下载连接数应为 1–16".into());
        }
        let dir = p["directory"]
            .as_str()
            .map(PathBuf::from)
            .unwrap_or(self.data.join("downloads"));
        if !dir.is_absolute() {
            return Err("下载目录必须是绝对路径".into());
        }
        if self.saved.downloads.len() >= 1000 {
            return Err("下载记录已达 1000 条，请先归档历史记录".into());
        }
        if self.saved.downloads.iter().any(|row| {
            row["directory"].as_str() == dir.to_str()
                && row["filename"] == name
                && !matches!(row["status"].as_str(), Some("complete" | "removed"))
        }) {
            return Err("同一目标文件已有任务，请恢复已有任务".into());
        }
        if dir.join(name).exists() {
            return Err("目标文件已存在；请更换文件名，恢复旧任务请使用继续下载".into());
        }
        let stem = name.split('.').next().unwrap_or("").to_uppercase();
        if matches!(
            stem.as_str(),
            "CON"
                | "PRN"
                | "AUX"
                | "NUL"
                | "COM1"
                | "COM2"
                | "COM3"
                | "COM4"
                | "COM5"
                | "COM6"
                | "COM7"
                | "COM8"
                | "COM9"
                | "LPT1"
                | "LPT2"
                | "LPT3"
                | "LPT4"
                | "LPT5"
                | "LPT6"
                | "LPT7"
                | "LPT8"
                | "LPT9"
        ) {
            return Err("不能使用 Windows 保留文件名".into());
        }
        let hash = p["sha256"].as_str().unwrap_or("");
        if !hash.is_empty() && (hash.len() != 64 || !hash.chars().all(|c| c.is_ascii_hexdigit())) {
            return Err("SHA-256 应为 64 位十六进制".into());
        }
        let gid = uuid::Uuid::new_v4().simple().to_string()[..16].to_owned();
        let mut options = json!({"dir":dir.to_string_lossy(),"out":name,"split":connections.to_string(),"max-connection-per-server":connections.to_string(),"min-split-size":"1M","gid":gid});
        if let Some(speed) = p["bytes_per_second"].as_u64() {
            options["max-download-limit"] = json!(speed.to_string());
        }
        if !hash.is_empty() {
            options["checksum"] = json!(format!("sha-256={hash}"));
        }
        if p["proxy"].as_bool() == Some(true) {
            if self.engines.proxy.is_none() {
                return Err("请先启动代理".into());
            }
            options["all-proxy"] = json!("http://127.0.0.1:17890");
        }
        let cipher = protect(&json!({"url":url,"options":options}).to_string()).await?;
        let record = json!({"gid":gid.clone(),"filename":name,"directory":dir.clone(),"host":parsed.host_str(),"sha256":hash,"protected_request":cipher,"status":"waiting","created":chrono::Utc::now().to_rfc3339()});
        self.saved.downloads.push(record);
        self.persist()?;
        self.engines.start_aria().await?;
        self.engines
            .aria_rpc("addUri", vec![json!([url]), options])
            .await?;
        self.event("transfer", "新增下载任务");
        self.persist()?;
        Ok(json!({"gid":gid,"filename":name,"directory":dir}))
    }
    pub async fn recover_downloads(&mut self) -> Reply {
        let saved = self.saved.downloads.clone();
        let mut recovered = 0;
        for row in saved {
            if matches!(row["status"].as_str(), Some("complete" | "removed")) {
                continue;
            }
            let gid = row["gid"].as_str().ok_or("下载记录缺少 ID")?;
            self.engines.start_aria().await?;
            if self
                .engines
                .aria_rpc("tellStatus", vec![json!(gid), json!(["gid"])])
                .await
                .is_ok()
            {
                continue;
            }
            let raw = unprotect(
                row["protected_request"]
                    .as_str()
                    .ok_or("下载记录缺少凭据")?,
            )
            .await?;
            let request: Value = serde_json::from_str(&raw).map_err(|_| "下载记录损坏")?;
            let mut options = request["options"].clone();
            options["pause"] = json!("true");
            self.engines
                .aria_rpc("addUri", vec![json!([request["url"]]), options])
                .await?;
            recovered += 1;
        }
        Ok(json!({"recovered":recovered,"paused":true}))
    }
    pub async fn download_snapshot(&mut self) -> Reply {
        let result = self.engines.downloads().await?;
        let active = result["tasks"].as_array().cloned().unwrap_or_default();
        let mut changed = false;
        for task in &active {
            if let Some(row) = self
                .saved
                .downloads
                .iter_mut()
                .find(|row| row["gid"] == task["gid"])
            {
                for key in [
                    "status",
                    "totalLength",
                    "completedLength",
                    "downloadSpeed",
                    "errorCode",
                ] {
                    if row[key] != task[key] {
                        row[key] = task[key].clone();
                        changed = true;
                    }
                }
            }
        }
        if changed {
            self.persist()?;
        }
        let mut tasks = active;
        for row in &self.saved.downloads {
            if !tasks.iter().any(|t| t["gid"] == row["gid"]) {
                let mut visible = row.clone();
                visible.as_object_mut().unwrap().remove("protected_request");
                if !matches!(
                    visible["status"].as_str(),
                    Some("complete" | "removed" | "error")
                ) {
                    visible["status"] = json!("recoverable");
                }
                tasks.push(visible);
            }
        }
        Ok(json!({"tasks":tasks,"running":result["running"]}))
    }
    pub async fn transfer_action(&mut self, p: Value) -> Reply {
        let result = self.engines.download_action(p.clone()).await?;
        if p["action"] == "cancel" {
            if let Some(row) = self
                .saved
                .downloads
                .iter_mut()
                .find(|r| r["gid"] == p["gid"])
            {
                row["status"] = json!("removed");
                self.persist()?;
            }
        }
        let _ = self.download_snapshot().await;
        Ok(json!({"result":result}))
    }
    pub async fn verify_download(&self, p: Value) -> Reply {
        let gid = p["gid"].as_str().ok_or("缺少任务 ID")?;
        let row = self
            .saved
            .downloads
            .iter()
            .find(|r| r["gid"] == gid)
            .ok_or("任务不存在")?;
        let path = PathBuf::from(row["directory"].as_str().ok_or("缺少目录")?)
            .join(row["filename"].as_str().ok_or("缺少文件名")?);
        let hash = tokio::task::spawn_blocking(move || -> Result<String, String> {
            use std::io::Read;
            let mut file = std::fs::File::open(path).map_err(|_| "文件不可读")?;
            let mut hasher = Sha256::new();
            let mut buffer = [0u8; 65536];
            loop {
                let count = file.read(&mut buffer).map_err(|_| "读取文件失败")?;
                if count == 0 {
                    break;
                }
                hasher.update(&buffer[..count]);
            }
            Ok(format!("{:x}", hasher.finalize()))
        })
        .await
        .map_err(|_| "校验任务失败")??;
        let expected = row["sha256"].as_str().unwrap_or("");
        Ok(
            json!({"gid":gid,"sha256":hash,"verified":if expected.is_empty(){Value::Null}else{json!(hash.eq_ignore_ascii_case(expected))}}),
        )
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn optimize_skips_builtin_targets_and_deduplicates() {
        // user:“继续进行网络工具插件的开发”+(自动选线只测真实节点，不把直连/拒绝当成代理线路)。
        let proxies = json!({
            "Auto":{"type":"Selector","now":"Tokyo","all":["DIRECT","REJECT","Tokyo","Auto2","Tokyo"]},
            "Tokyo":{"type":"Shadowsocks","history":[{"delay":26}]}
        });
        assert_eq!(
            selector_members(&proxies, "Auto").unwrap(),
            vec!["Tokyo".to_string(), "Auto2".to_string()]
        );
        assert!(selector_members(&proxies, "Tokyo").is_err());
        assert!(selector_members(&proxies, "Missing").is_err());
    }
    #[test]
    fn optimize_ranks_reachable_nodes_by_delay_and_ignores_failures() {
        let rows = rank_candidates(vec![
            json!({"name":"Tokyo","delay":58}),
            json!({"name":"Broken","error":"超时"}),
            json!({"name":"Osaka","delay":26}),
            json!({"name":"Seoul","delay":26}),
        ]);
        assert_eq!(rows[0]["name"], "Osaka");
        assert_eq!(rows[1]["name"], "Seoul");
        assert_eq!(rows[3]["name"], "Broken");
        assert_eq!(pick_fastest(&rows), Some(("Osaka".to_string(), 26u64)));
    }
    #[tokio::test]
    async fn status_reports_whether_a_proxy_configuration_is_saved() {
        // user:“添加不了订阅”“把操作傻瓜化”+(首页据此决定先显示添加订阅还是直接开启代理)。
        let data =
            std::env::temp_dir().join(format!("sunday-network-engines-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&data).unwrap();
        let mut engines = Engines::new(data.clone()).unwrap();
        assert_eq!(engines.proxy_status().await["config_saved"], false);
        std::fs::write(data.join("proxy.config.secure"), b"stub").unwrap();
        assert_eq!(engines.proxy_status().await["config_saved"], true);
        std::fs::remove_dir_all(data).unwrap();
    }
    #[test]
    fn common_acceleration_rules_precede_subscription_rules() {
        // user:“点一下‘一键加速’，然后就把 GitHub等常用的那些网站全部都加速了”+(内置站点优先于订阅规则)。
        let mut config: serde_yaml::Value = serde_yaml::from_str(
            "proxy-groups:\n  - name: 节点选择\n    type: select\n    proxies: [a]\nrules:\n  - MATCH,DIRECT\n",
        )
        .unwrap();
        apply_common_acceleration(&mut config).unwrap();
        let rules = config["rules"].as_sequence().unwrap();
        assert_eq!(
            rules[0].as_str(),
            Some("DOMAIN-SUFFIX,github.com,节点选择")
        );
        assert_eq!(rules.last().unwrap().as_str(), Some("MATCH,DIRECT"));
        assert!(rules
            .iter()
            .any(|rule| rule.as_str() == Some("DOMAIN-SUFFIX,huggingface.co,节点选择")));
    }
    #[test]
    fn common_acceleration_leaves_configs_without_a_target_unchanged() {
        let mut config: serde_yaml::Value =
            serde_yaml::from_str("rules:\n  - MATCH,DIRECT\n").unwrap();
        apply_common_acceleration(&mut config).unwrap();
        assert_eq!(config["rules"].as_sequence().unwrap().len(), 1);
    }
    #[test]
    fn proxy_api_paths_keep_the_group_and_node_segments() {
        // user:“ValueError: Mihomo 返回 404”+(节点/分组名必须作为独立路径段传给 Mihomo)。
        let mut url = reqwest::Url::parse("http://localhost/proxies").unwrap();
        url.path_segments_mut().unwrap().push("GLOBAL");
        assert_eq!(url.path(), "/proxies/GLOBAL");
        let mut url = reqwest::Url::parse("http://localhost/proxies").unwrap();
        url.path_segments_mut().unwrap().push("US-CF-BOOT").push("delay");
        assert_eq!(url.path(), "/proxies/US-CF-BOOT/delay");
    }
    #[test]
    fn subscription_proxy_prefers_https_and_skips_the_plugin_port() {
        // user:“https://sub.serverpulse.me/clash.yaml一直正在处理，始终没有添加”+(订阅下载优先走系统代理，避开插件自己的端口)。
        assert_eq!(
            subscription_proxy("http=127.0.0.1:7890;https=127.0.0.1:7891"),
            Some("127.0.0.1:7891".to_string())
        );
        assert_eq!(
            subscription_proxy("127.0.0.1:7890"),
            Some("127.0.0.1:7890".to_string())
        );
        assert_eq!(subscription_proxy("127.0.0.1:17890"), None);
        assert_eq!(subscription_proxy(""), None);
    }
    #[test]
    fn imported_config_cannot_enable_tun_or_remote_api() {
        let value:Value=serde_yaml::from_str(&sanitize_config("mixed-port: 9000\nallow-lan: true\nexternal-controller: 0.0.0.0:1234\ntun:\n  enable: true\n",4000,"secret").unwrap()).unwrap();
        assert_eq!(value["tun"]["enable"], false);
        assert_eq!(value["allow-lan"], false);
        assert_eq!(value["external-controller"], "127.0.0.1:4000");
        assert_eq!(value["secret"], "secret");
    }
}
