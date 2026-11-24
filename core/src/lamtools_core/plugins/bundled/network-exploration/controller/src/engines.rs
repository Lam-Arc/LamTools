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
    /// (同时下载数, 失败重试次数, 全局限速字节/秒)，由 Controller 在启动前写入。
    pub download: (u64, u64, u64),
}
enum AriaRpcError {
    Rejected,
    Unconfirmed(&'static str),
}

impl AriaRpcError {
    fn message(&self) -> &'static str {
        match self {
            Self::Rejected => "aria2 操作失败，请检查任务状态、文件权限或链接有效期",
            Self::Unconfirmed(message) => message,
        }
    }
}

// user:“失败任务显示具体原因”+(aria2 的错误码翻成人话，界面不再只说「链接可能失效」)。
pub fn aria_error_text(code: &str) -> String {
    match code {
        "1" => "下载内核报告未知错误",
        "2" => "连接超时，源站没有在限定时间内响应",
        "3" => "源站返回 404，文件不存在或链接已失效",
        "4" => "连续多次找不到资源，链接可能已失效",
        "5" => "下载速度过慢，被内核判定为失败",
        "6" => "网络连接中断，请检查网络后继续",
        "7" => "下载未完成，可以继续续传",
        "8" => "源站不支持断点续传，只能重新下载",
        "9" => "磁盘空间不足",
        "10" => "分片长度不匹配，源文件可能已经变化",
        "11" => "同一个文件正在下载中",
        "13" => "目标文件已存在",
        "16" => "无法创建文件，请检查目录权限",
        "17" => "文件系统错误，请检查磁盘或目录",
        "18" => "无法创建下载目录",
        "19" => "域名解析失败，请检查 DNS 或网络",
        "22" => "源站返回了无法识别的响应头",
        "23" => "重定向次数过多",
        "24" => "源站要求认证，链接可能过期或需要登录",
        "29" => "源站无法处理这个请求，可能是临时故障",
        "31" => "文件校验失败，内容和预期不一致",
        _ => "下载失败，请检查链接与网络后重试",
    }
    .to_string()
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
        let left = a["delay"]
            .as_u64()
            .filter(|value| *value > 0)
            .unwrap_or(u64::MAX);
        let right = b["delay"]
            .as_u64()
            .filter(|value| *value > 0)
            .unwrap_or(u64::MAX);
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
    match client.get(url).bearer_auth(&secret).send().await {
        Ok(response) if response.status().is_success() => {
            let value: Value = response.json().await.unwrap_or_default();
            match value["delay"].as_u64().filter(|delay| *delay > 0) {
                Some(delay) => {
                    json!({"name":name,"delay":delay,"ms":started.elapsed().as_millis() as u64})
                }
                None => json!({"name":name,"error":"测速未返回延迟"}),
            }
        }
        Ok(response) if response.status().as_u16() == 404 => {
            // user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(provider 下发的节点不在 /proxies 顶层，普通测速接口 404；改走 provider 健康检查再回读延迟，否则这些线路永远显示未测速)。
            match provider_delay_probe(client, port, &secret, &name, &target).await {
                Ok(delay) => json!({"name":name,"delay":delay,"ms":started.elapsed().as_millis() as u64}),
                Err(error) => json!({"name":name,"error":error}),
            }
        }
        Ok(response) => {
            json!({"name":name,"error":format!("节点返回 {}",response.status().as_u16())})
        }
        Err(_) => json!({"name":name,"error":"测速请求失败或超时"}),
    }
}
async fn fetch_providers(
    client: &reqwest::Client,
    port: u16,
    secret: &str,
) -> Result<Value, String> {
    let response = client
        .get(format!("http://127.0.0.1:{port}/providers/proxies"))
        .bearer_auth(secret)
        .send()
        .await
        .map_err(|_| "控制接口不可用".to_string())?;
    if !response.status().is_success() {
        return Err("控制接口不可用".into());
    }
    response
        .json::<Value>()
        .await
        .map_err(|_| "控制接口返回无效数据".to_string())
}
/// user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(先定位这个节点属于哪个 provider，才能触发它的健康检查)。
fn provider_of(providers: &Value, name: &str) -> Option<String> {
    let groups = providers["providers"].as_object()?;
    for (key, provider) in groups {
        let Some(nodes) = provider["proxies"].as_array() else {
            continue;
        };
        if nodes
            .iter()
            .any(|node| node["name"].as_str() == Some(name) && node["provider-name"].as_str().is_some())
        {
            return Some(key.clone());
        }
    }
    None
}
/// user:“延迟正常显示”+(provider 健康检查不返回延迟本身，测完要回读该节点的历史)。
fn last_delay(providers: &Value, name: &str) -> Option<u64> {
    let groups = providers["providers"].as_object()?;
    for provider in groups.values() {
        let Some(nodes) = provider["proxies"].as_array() else {
            continue;
        };
        for node in nodes {
            if node["name"].as_str() != Some(name) {
                continue;
            }
            let history = node["history"].as_array()?;
            for entry in history.iter().rev() {
                if let Some(delay) = entry["delay"].as_u64().filter(|value| *value > 0) {
                    return Some(delay);
                }
            }
        }
    }
    None
}
async fn provider_delay_probe(
    client: reqwest::Client,
    port: u16,
    secret: &str,
    name: &str,
    target: &str,
) -> Result<u64, String> {
    let before = fetch_providers(&client, port, secret).await?;
    let provider = provider_of(&before, name).ok_or("线路不在任何订阅提供器里")?;
    let mut url = reqwest::Url::parse(&format!("http://127.0.0.1:{port}/providers/proxies"))
        .map_err(|_| "测速地址无效".to_string())?;
    url.path_segments_mut()
        .map_err(|_| "测速地址无效".to_string())?
        .push(&provider)
        .push(name)
        .push("healthcheck");
    url.query_pairs_mut()
        .append_pair("timeout", "5000")
        .append_pair("url", target);
    let _ = client
        .get(url)
        .bearer_auth(secret)
        .send()
        .await
        .map_err(|_| "测速请求失败或超时".to_string())?;
    let after = fetch_providers(&client, port, secret).await?;
    last_delay(&after, name).ok_or_else(|| "线路不可达".to_string())
}
/// user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(provider 节点只在 /providers/proxies 里，按名字并进主表；同名以内联节点为准，provider 不覆盖)。
fn merge_provider_nodes(table: &mut serde_json::Map<String, Value>, providers: &Value) -> usize {
    let Some(groups) = providers["providers"].as_object() else {
        return 0;
    };
    let mut added = 0;
    for provider in groups.values() {
        let Some(nodes) = provider["proxies"].as_array() else {
            continue;
        };
        for node in nodes {
            let Some(name) = node["name"].as_str() else {
                continue;
            };
            if name.is_empty() || table.contains_key(name) {
                continue;
            }
            table.insert(name.to_string(), node.clone());
            added += 1;
        }
    }
    added
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
            download: (3, 5, 0),
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
            Err(_) => {
                json!({"running":true,"healthy":false,"traffic_source":"mihomo_only","started_at":started,"config_saved":config_saved})
            }
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
        // user:“改名儿是小事儿 主要是够不够 easy 和Stable”+(内核起不来时必须尽快给出原因；原来最多等 50 次、每次带 8 秒超时，会超过宿主 90 秒上限，整个插件被判死)。
        let deadline = Instant::now() + Duration::from_secs(20);
        loop {
            if self.proxy_request("GET", "/version", None).await.is_ok() {
                self.proxy_started = Some(chrono::Utc::now());
                return Ok(
                    json!({"running":true,"mixed_port":17890,"tun":false,"system_proxy":false}),
                );
            }
            let exited = self
                .proxy
                .as_mut()
                .map(|process| process.try_wait().ok().flatten().is_some())
                .unwrap_or(true);
            if exited {
                self.proxy = None;
                self.proxy_started = None;
                return Err("Mihomo 启动后立即退出：配置、规则资源或本地端口不可用".into());
            }
            if Instant::now() >= deadline {
                break;
            }
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
        self.stop_proxy().await?;
        Err("Mihomo 启动超时：检查配置、规则资源或本地端口".into())
    }
    pub async fn stop_proxy(&mut self) -> Reply {
        terminate(&mut self.proxy).await;
        self.proxy_started = None;
        let _ = tokio::fs::remove_file(self.data.join("runtime/mihomo.yaml")).await;
        Ok(json!({"running":false}))
    }
    pub async fn proxy_inspect(&self) -> Reply {
        let mut proxies = self.proxy_request("GET", "/proxies", None).await?["proxies"].clone();
        let rules = self.proxy_request("GET", "/rules", None).await?;
        let configs = self.proxy_request("GET", "/configs", None).await?;
        // user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(订阅用 proxy-providers 下发节点时，/proxies 顶层不列这些节点，界面因此永远显示未测速；把 provider 节点并进同一张表，延迟和切换才有数据)。
        if let Ok(providers) = self.proxy_request("GET", "/providers/proxies", None).await {
            if let Some(table) = proxies.as_object_mut() {
                merge_provider_nodes(table, &providers);
            }
        }
        Ok(
            json!({"proxies":proxies,"rules":rules["rules"],"mode":configs["mode"],"mixed_port":configs["mixed-port"]}),
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
        let direct = self
            .proxy_request(
                "GET",
                &format!("{}?{}", url.path(), url.query().unwrap()),
                None,
            )
            .await;
        match direct {
            Ok(value) => Ok(value),
            // user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(provider 节点在 /proxies 上测速会 404，这里回退到所属 provider 的健康检查，界面上单行测速才不会整列失败)。
            Err(error) if error.contains("404") => {
                match provider_delay_probe(
                    self.client.clone(),
                    self.proxy_port,
                    &self.secret,
                    name,
                    target,
                )
                .await
                {
                    Ok(delay) => Ok(json!({"delay":delay})),
                    Err(message) => Err(format!("{error}（{message}）")),
                }
            }
            Err(error) => Err(error),
        }
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
                self.proxy_select(json!({"group":group,"name":name}))
                    .await?;
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
        self.aria_rpc_outcome(method, params)
            .await
            .map_err(|error| error.message().to_string())
    }

    // user:“修”+(明确拒绝和回执丢失分开处理，后者可能已在下载)。
    async fn aria_rpc_outcome(
        &self,
        method: &str,
        params: Vec<Value>,
    ) -> Result<Value, AriaRpcError> {
        let mut args = vec![json!(format!("token:{}", self.secret))];
        args.extend(params);
        let response = self
            .client
            .post(format!("http://127.0.0.1:{}/jsonrpc", self.aria_port))
            .json(&json!({
                "jsonrpc": "2.0", "id": "sunday", "method": format!("aria2.{method}"), "params": args
            }))
            .send()
            .await
            .map_err(|_| AriaRpcError::Unconfirmed("aria2 控制接口不可用"))?;
        let value: Value = response
            .json()
            .await
            .map_err(|_| AriaRpcError::Unconfirmed("aria2 返回无效数据"))?;
        if value["error"].is_object() {
            return Err(AriaRpcError::Rejected);
        }
        value
            .get("result")
            .cloned()
            .ok_or(AriaRpcError::Unconfirmed("aria2 返回无效数据"))
    }
    async fn start_aria(&mut self) -> Result<(), String> {
        if let Some(process) = self.aria.as_mut() {
            if process.try_wait().map_err(|e| e.to_string())?.is_none() {
                return Ok(());
            }
        }
        self.aria_port = free_port()?;
        // user:“并发数量、限速、重试策略可设置”+(设置页保存的值在启动内核时生效)。
        let (concurrency, max_tries, overall_limit) = self.download;
        let binary = self.binary("aria2c")?;
        self.aria = Some(
            command(binary)
                // user:“修”+(下载线路由统一服务明确选择，不受启动进程的环境代理干扰)。
                .env_remove("http_proxy")
                .env_remove("https_proxy")
                .env_remove("all_proxy")
                .env_remove("no_proxy")
                .env_remove("HTTP_PROXY")
                .env_remove("HTTPS_PROXY")
                .env_remove("ALL_PROXY")
                .env_remove("NO_PROXY")
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
                    &format!("--max-tries={max_tries}"),
                    "--retry-wait=3",
                    &format!("--max-concurrent-downloads={concurrency}"),
                    "--check-certificate=true",
                    &format!("--max-overall-download-limit={overall_limit}"),
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
    &[
        "github.com",
        "github.dev",
        "api.github.com",
        "github.githubassets.com",
        "githubusercontent.com",
        "githubapp.com",
        "github.io",
        "education.github.com",
        "resources.github.com",
        "uploads.github.com",
        "archivalprogram.github.com",
        "hub.docker.com",
        "greasyfork.org",
    ],
    &[
        "steamcommunity.com",
        "store.steampowered.com",
        "steamstatic.com",
        "steamcdn-a.akamaihd.net",
        "media.steampowered.com",
    ],
    &[
        "twitch.tv",
        "irc-ws.chat.twitch.tv",
        "passport.twitch.tv",
        "assets.twitch.tv",
        "clips-media-assets2.twitch.tv",
        "id.twitch.tv",
        "pubsub-edge.twitch.tv",
        "panels.twitch.tv",
        "supervisor-ext.twitch.tv",
    ],
    &["spotify.com", "open.spotify.com"],
    &[
        "google.com",
        "www.google.com",
        "translate.google.cn",
        "translate.googleapis.com",
        "fonts.gstatic.com",
        "fonts.googleapis.com",
        "themes.googleusercontent.com",
        "ajax.googleapis.com",
    ],
    &["huggingface.co"],
    &[
        "dropbox.com",
        "dl.dropboxusercontent.com",
        "mega.co.nz",
        "mega.io",
        "mega.nz",
        "onedrive.live.com",
        "storage.live.com",
    ],
    &[
        "nexusmods.com",
        "mod.io",
        "binarylage.mod.io",
        "files.nexus-cdn.com",
        "fandom.com",
        "pinterest.com",
        "artstation.com",
        "imgur.com",
        "vercel.app",
    ],
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
            if matches!(
                kind,
                "select" | "url-test" | "fallback" | "load-balance" | "relay"
            ) && usable(name)
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
                preset.into_iter().map(serde_yaml::Value::String).collect(),
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
    if candidate.is_empty() || candidate == "127.0.0.1:17890" || candidate == "localhost:17890" {
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
    // user:“修”+(加速启停时同步自动下载任务的端口，不能让重试请求继续访问已关闭的服务)。
    pub async fn reroute_auto_downloads(&mut self, port: Option<u16>) -> Result<(), String> {
        let tasks = self.engines.downloads().await?["tasks"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let (_, proxy_url) = crate::transfer::route(&json!({}), port, false)?;
        for task in tasks {
            if !matches!(
                task["status"].as_str(),
                Some("active" | "waiting" | "paused")
            ) {
                continue;
            }
            if self
                .saved
                .downloads
                .iter()
                .any(|row| row["gid"] == task["gid"] && row["route"] == "auto")
            {
                self.engines
                    .aria_rpc(
                        "changeOption",
                        vec![task["gid"].clone(), json!({"all-proxy":proxy_url})],
                    )
                    .await?;
            }
        }
        Ok(())
    }
    pub async fn add_download(&mut self, p: Value) -> Reply {
        let p = crate::transfer::normalize(p)?;
        let (route, proxy_url) = crate::transfer::route(
            &p,
            (self.accelerator.port > 0).then_some(self.accelerator.port),
            self.engines.proxy.is_some(),
        )?;
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
        // user:“知不知道怎么修改下载默认位置”+(设置里存了默认目录就用它，没存才回落到插件私有目录)。
        let configured = self.saved.settings["download"]["directory"]
            .as_str()
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(PathBuf::from);
        let dir = p["directory"]
            .as_str()
            .map(PathBuf::from)
            .or(configured)
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
        options["all-proxy"] = json!(proxy_url);
        // user:“接管时把 Cookie 和 User-Agent 传给 aria2”+(请求头只进加密请求记录，不回传、不写日志)。
        let header_lines = crate::transfer::header_lines(&p["headers"]);
        if !header_lines.is_empty() {
            options["header"] = json!(header_lines);
        }
        let source = p["source"].as_str().unwrap_or("page");
        let cipher = protect(&json!({"url":url,"options":options}).to_string()).await?;
        let record = json!({"gid":gid.clone(),"filename":name,"directory":dir.clone(),"host":parsed.host_str(),"route":route,"source":source,"sha256":hash,"protected_request":cipher,"status":"waiting","created":chrono::Utc::now().to_rfc3339()});
        // user:“修”+(先确认内核可用，再记录任务。明确拒绝时释放文件名，回执不明时保留任务供恢复)。
        self.apply_download_settings();
        self.engines.start_aria().await?;
        self.saved.downloads.push(record);
        if let Err(error) = self.persist() {
            self.saved.downloads.pop();
            return Err(error);
        }
        let outcome = self
            .engines
            .aria_rpc_outcome("addUri", vec![json!([url]), options])
            .await;
        let status = match outcome {
            Ok(result) if result.as_str() == Some(gid.as_str()) => "waiting",
            Err(AriaRpcError::Rejected) => {
                let rejected = self.saved.downloads.pop().expect("just persisted this download");
                if self.persist().is_ok() {
                    return Err(AriaRpcError::Rejected.message().into());
                }
                self.saved.downloads.push(rejected);
                "recoverable"
            }
            _ => "recoverable",
        };
        let message = if status == "waiting" { "新增下载任务" } else { "下载任务等待确认" };
        self.event("transfer", message);
        // The task is already durable. A failure to save the activity log must not trigger a second download.
        let _ = self.persist();
        Ok(json!({"gid":gid,"filename":name,"directory":dir,"route":route,"status":status}))
    }
    pub async fn recover_downloads(&mut self) -> Reply {
        let saved = self.saved.downloads.clone();
        let mut recovered = 0;
        for row in saved {
            if matches!(row["status"].as_str(), Some("complete" | "removed")) {
                continue;
            }
            let gid = row["gid"].as_str().ok_or("下载记录缺少 ID")?;
            self.apply_download_settings();
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
            // user:“修”+(重启后根据当前服务重新选择线路，不复用已经失效的随机端口)。
            let routing = if row.get("route").is_some() {
                json!({"route":row["route"]})
            } else {
                json!({"proxy":options["all-proxy"] == "http://127.0.0.1:17890"})
            };
            let (_, proxy_url) = crate::transfer::route(
                &routing,
                (self.accelerator.port > 0).then_some(self.accelerator.port),
                true,
            )?;
            options["all-proxy"] = json!(proxy_url);
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
        // user:“修”+(状态接口与列表接口返回同一份包含文件信息的任务快照)。
        let mut tasks: Vec<Value> = active
            .into_iter()
            .map(|task| {
                let mut merged = self
                    .saved
                    .downloads
                    .iter()
                    .find(|row| row["gid"] == task["gid"])
                    .cloned()
                    .unwrap_or(json!({}));
                merged.as_object_mut().unwrap().remove("protected_request");
                if let Some(fields) = task.as_object() {
                    merged.as_object_mut().unwrap().extend(fields.clone());
                }
                merged
            })
            .collect();
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
        // user:“失败任务显示具体原因及恢复操作”+(错误码翻成人话，并标出这个来源能不能续传)。
        for task in tasks.iter_mut() {
            let code = task["errorCode"].as_str().unwrap_or("").to_string();
            if task["status"] == "error" {
                task["errorText"] = json!(aria_error_text(&code));
            }
            if code == "8" {
                task["canResume"] = json!(false);
            }
        }
        Ok(json!({"tasks":tasks,"running":result["running"]}))
    }
    pub async fn transfer_action(&mut self, p: Value) -> Reply {
        if p["action"] == "resume" {
            // user:“修”+(继续任务时重新选择当前端口；明确选代理但代理未启动时给出一致错误)。
            if let Some(row) = self
                .saved
                .downloads
                .iter()
                .find(|row| row["gid"] == p["gid"])
            {
                let routing = row
                    .get("route")
                    .map(|mode| json!({"route":mode}))
                    .unwrap_or(json!({}));
                let (_, proxy_url) = crate::transfer::route(
                    &routing,
                    (self.accelerator.port > 0).then_some(self.accelerator.port),
                    self.engines.proxy.is_some(),
                )?;
                self.engines
                    .aria_rpc(
                        "changeOption",
                        vec![p["gid"].clone(), json!({"all-proxy":proxy_url})],
                    )
                    .await?;
            }
        }
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
    fn aria_error_codes_become_actionable_reasons() {
        // user:“失败任务显示具体原因”+(常见错误码必须给出可执行原因，未知码也要有兜底)。
        assert!(aria_error_text("3").contains("404"));
        assert!(aria_error_text("6").contains("中断"));
        assert!(aria_error_text("8").contains("续传"));
        assert!(aria_error_text("9").contains("磁盘"));
        assert!(aria_error_text("19").contains("解析"));
        assert!(aria_error_text("24").contains("认证"));
        assert!(aria_error_text("999").contains("重试"));
    }
    #[tokio::test]
    async fn failed_download_reports_a_readable_reason() {
        // user:“失败任务显示具体原因及恢复操作”+(任务列表里直接带 errorText，界面不必自己猜)。
        let dir = std::env::temp_dir().join(format!("failed-download-{}", uuid::Uuid::new_v4()));
        let mut controller = crate::state::Controller::new(dir.clone()).unwrap();
        controller.saved.downloads.push(json!({"gid":"bad", "filename":"x.zip", "status":"error", "errorCode":"3"}));
        let list = controller.call("transfer.list", json!({})).await.unwrap();
        let row = &list["tasks"][0];
        assert_eq!(row["status"], "error");
        assert!(row["errorText"].as_str().unwrap().contains("404"));
        std::fs::remove_dir_all(dir).unwrap();
    }
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
        assert_eq!(rules[0].as_str(), Some("DOMAIN-SUFFIX,github.com,节点选择"));
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
        url.path_segments_mut()
            .unwrap()
            .push("US-CF-BOOT")
            .push("delay");
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
    #[test]
    fn provider_nodes_join_the_main_table_with_their_delays() {
        // user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(provider 下发的节点必须能和内联节点一样出现在线路表里，并带着实测延迟)。
        let mut table = json!({"US-CF-BOOT":{"type":"Trojan","history":[{"delay":180}]}})
            .as_object()
            .cloned()
            .unwrap();
        let providers = json!({"providers":{
            "cf-nodes":{"proxies":[
                {"name":"CF-1","type":"Trojan","history":[{"delay":562}]},
                {"name":"CF-2","type":"Trojan","history":[{"delay":0}]}
            ]},
            "cf-nodes-us":{"proxies":[{"name":"US-CF-8","type":"Trojan","history":[{"delay":422}]}]}
        }});
        assert_eq!(merge_provider_nodes(&mut table, &providers), 3);
        assert_eq!(table["CF-1"]["history"][0]["delay"], 562);
        assert_eq!(table["US-CF-8"]["history"][0]["delay"], 422);
        assert_eq!(table["US-CF-BOOT"]["history"][0]["delay"], 180);
    }
    #[test]
    fn provider_nodes_never_override_inline_nodes_or_break_on_missing_data() {
        let mut table = json!({"CF-1":{"type":"Trojan","history":[{"delay":100}]}})
            .as_object()
            .cloned()
            .unwrap();
        let providers = json!({"providers":{"cf-nodes":{"proxies":[
            {"name":"CF-1","type":"Trojan","history":[{"delay":999}]},
            {"type":"Trojan"}
        ]}}});
        assert_eq!(merge_provider_nodes(&mut table, &providers), 0);
        assert_eq!(table["CF-1"]["history"][0]["delay"], 100);
        assert_eq!(merge_provider_nodes(&mut table, &json!({})), 0);
    }
    #[test]
    fn provider_lookup_finds_the_owner_and_reads_the_latest_delay() {
        // user:“延迟正常显示”+(provider 健康检查不返回延迟，必须先按节点名找到所属 provider，测完再回读它自己的历史)。
        let providers = json!({"providers":{
            "Proxy":{"proxies":[{"name":"美国","type":"URLTest","history":[]}]},
            "cf-nodes":{"proxies":[
                {"name":"CF-1","provider-name":"cf-nodes","history":[{"delay":0},{"delay":562}]},
                {"name":"CF-2","provider-name":"cf-nodes","history":[{"delay":0}]}
            ]}
        }});
        assert_eq!(provider_of(&providers, "CF-1"), Some("cf-nodes".to_string()));
        assert_eq!(provider_of(&providers, "CF-2"), Some("cf-nodes".to_string()));
        assert_eq!(provider_of(&providers, "美国"), None);
        assert_eq!(provider_of(&providers, "no-such-node"), None);
        assert_eq!(last_delay(&providers, "CF-1"), Some(562));
        assert_eq!(last_delay(&providers, "CF-2"), None);
        assert_eq!(last_delay(&json!({}), "CF-1"), None);
    }
}
