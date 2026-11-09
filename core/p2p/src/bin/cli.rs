//! A tiny driver for the transport.
//!
//! user:“先打通两台设备之间的真实连接与远程会话，再完善设备管理和交互体验”+(这个
//! 命令就是"真实连接"的最小可验证入口：一台服务，一台连上去问一个问题)。

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{bail, Context, Result};
use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use sunday_p2p::{encode_ticket, Client, Identity, ServerLink, TrustStore};
use tokio::sync::Mutex;

#[tokio::main]
async fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("serve") => serve(args.collect()).await,
        Some("call") => call(args.collect()).await,
        Some("qr") => qr(args.collect()),
        Some("scan") => scan(args.collect()),
        _ => {
            println!("{}", USAGE);
            Ok(())
        }
    }
}

// user:“验收：打印的 USAGE 里出现 qr 和 scan”+(帮助文本必须列出所有子命令，否则按帮助
// 判断二进制能力会得出"没有二维码功能"的错误结论)。
const USAGE: &str = "sunday-p2p serve --dir <dir> --name <name>\n\
                     sunday-p2p call --dir <dir> --name <name> --ticket <ticket> [--method ping] [--params '{}']\n\
                     sunday-p2p qr --ticket <ticket>\n\
                     sunday-p2p scan --file <image>";

struct Flags {
    dir: PathBuf,
    name: String,
    ticket: String,
    method: String,
    params: String,
    core_port: u16,
    core_token: String,
    watch: u64,
    file: String,
}

fn parse(args: Vec<String>) -> Result<Flags> {
    let mut flags = Flags {
        dir: PathBuf::from("."),
        name: hostname(),
        ticket: String::new(),
        method: "ping".to_owned(),
        params: "{}".to_owned(),
        core_port: 0,
        core_token: String::new(),
        watch: 0,
        file: String::new(),
    };
    let mut iter = args.into_iter();
    while let Some(flag) = iter.next() {
        let mut value = || iter.next().context(format!("{flag} needs a value"));
        match flag.as_str() {
            "--dir" => flags.dir = PathBuf::from(value()?),
            "--name" => flags.name = value()?,
            "--ticket" => flags.ticket = value()?,
            "--method" => flags.method = value()?,
            "--params" => flags.params = value()?,
            "--core-port" => flags.core_port = value()?.parse()?,
            "--core-token" => flags.core_token = value()?,
            "--watch" => flags.watch = value()?.parse()?,
            "--file" => flags.file = value()?,
            other => bail!("unknown flag {other}"),
        }
    }
    Ok(flags)
}

fn hostname() -> String {
    std::env::var("COMPUTERNAME")
        .or_else(|_| std::env::var("HOSTNAME"))
        .unwrap_or_else(|_| "device".to_owned())
}

/// Prints the ticket as an SVG QR code.
///
/// The desktop host does not link this crate: iroh pulls windows crates that clash with the
/// app's own, so the host asks this same binary for the image instead of growing a second
/// QR implementation.
fn qr(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.ticket.trim().is_empty() {
        bail!("--ticket is required");
    }
    print!("{}", sunday_p2p::ticket_qr_svg(&flags.ticket)?);
    Ok(())
}
/// Decodes a QR photo into the ticket it carries.
fn scan(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.file.trim().is_empty() {
        bail!("--file is required");
    }
    let ticket = sunday_p2p::scan_qr_file(std::path::Path::new(&flags.file))?;
    println!("{ticket}");
    Ok(())
}

/// 传输进程自己的日志：宿主不读管道时，这里仍然留下对端连接和中继状态。
fn diary(dir: &std::path::Path, line: &str) {
    use std::io::Write;
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("p2p.log"))
    {
        let _ = writeln!(file, "{line}");
        let _ = file.flush();
    }
}

async fn serve(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    let identity = Identity::load_or_create(&flags.dir)?;
    let endpoint = identity.endpoint().await?;
    // 出票前等中继就绪，否则票据里只有当时的局域网地址。
    let addr = sunday_p2p::dialable_addr(&endpoint, std::time::Duration::from_secs(10)).await;
    let ticket = encode_ticket(&addr)?;
    let trust = Arc::new(Mutex::new(TrustStore::load(&flags.dir)?));
    println!("NAME {}", flags.name);
    println!("ID {}", endpoint.id());
    println!("TICKET {ticket}");
    // user:“票据就是完整控制权”+(拿到它的人可以调用 Core 的任何 RPC，包括执行工具。
    // 日志会被复制出去排障，所以默认只记前缀；要用日志里的票据做实验时显式开环境变量)。
    let logged_ticket = if std::env::var("SUNDAY_P2P_LOG_TICKET").ok().as_deref() == Some("1") {
        ticket.clone()
    } else {
        format!("{}…", &ticket[..ticket.len().min(24)])
    };
    diary(&flags.dir, &format!("TICKET {logged_ticket}"));
    for line in sunday_p2p::relay_summary(&endpoint) {
        println!("RELAY {line}");
        diary(&flags.dir, &format!("RELAY {line}"));
    }
    // 网络切换后地址会变：把新票据直接再打一行，宿主读到就更新二维码。
    {
        let endpoint = endpoint.clone();
        let mut last = ticket.clone();
        tokio::spawn(async move {
            use iroh::Watcher as _;
            let mut watcher = endpoint.watch_addr();
            loop {
                let addr = match watcher.updated().await {
                    Ok(addr) => addr,
                    Err(_) => break,
                };
                let Ok(next) = encode_ticket(&addr) else { continue };
                if next != last {
                    last = next.clone();
                    println!("TICKET {next}");
                }
            }
        });
    }
    println!("READY");

    loop {
        // user:“第一次连的时候连上了，后面就没有再连上过”“连上了之后也报错”+(实测传输
        // 进程会在一次握手超时之后直接退出，进程一死，电脑这边就再也接不到任何设备；
        // 一次失败的握手只说明这一次没成，记一笔继续等下一台)。
        let mut link = match ServerLink::accept(&endpoint, Arc::clone(&trust), &flags.name).await {
            Ok(Some(link)) => link,
            Ok(None) => return Ok(()),
            Err(error) => {
                let line = format!("ACCEPT ERROR {error:#}");
                eprintln!("{line}");
                diary(&flags.dir, &line);
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                continue;
            }
        };
        println!("PEER {} trusted={}", link.peer, link.trusted);
        diary(&flags.dir, &format!("PEER {} trusted={}", link.peer, link.trusted));
        if !link.trusted {
            // user:“允许撤销授权”+(被撤销的设备在握手里已经拿到 trusted=false，这里主动收掉，
            // 对端会看到「已被撤销」而不是一句看不懂的 closed by peer)。
            println!("PEER-REJECTED {}", link.peer);
            diary(&flags.dir, &format!("PEER-REJECTED {}", link.peer));
            link.close();
            continue;
        }
        // 每来一台设备就起一条事件泵：Core 的通知按帧推回给对端。
        let log_dir = flags.dir.clone();
        let name = flags.name.clone();
        let core_port = flags.core_port;
        let core_token = flags.core_token.clone();
        let pump_token = flags.core_token.clone();
        // user:“连上电脑了之后也没有出现项目”+(界面读项目、会话、工作台快照走的是 Core 的
        // JSON-RPC；这条通道不和事件共用一条 socket，免得大回复把事件流堵住)。
        // user:“电脑那边一重启，手机上就全是错”+(Core 换端口重启会让这条桥的 socket 断掉。
        // 桥放在 Mutex<Option<...>> 里，死掉时由下一条 RPC 就地重建，而不是让手机上的
        // 每条调用都报「RPC 通道已关闭」直到重新配对)。
        let rpc: Arc<Mutex<Option<Arc<sunday_p2p::rpc::CoreRpc>>>> = Arc::new(Mutex::new(
            match core_port {
                0 => None,
                port => match sunday_p2p::rpc::CoreRpc::connect(port, &core_token).await {
                    Ok(bridge) => Some(Arc::new(bridge)),
                    Err(error) => {
                        let line = format!("RPC-CHANNEL ERROR {error:#}");
                        eprintln!("{line}");
                        diary(&log_dir, &line);
                        None
                    }
                },
            },
        ));
        tokio::spawn(async move {
        let closed = Arc::new(tokio::sync::Mutex::new(false));
        // 最近一次被界面订阅的会话，事件丢帧时用它告诉界面该重新 resume 哪一条。
        let last_thread: Arc<tokio::sync::Mutex<Option<String>>> =
            Arc::new(tokio::sync::Mutex::new(None));
        if rpc.lock().await.is_some() {
            // user:“请立即回复你好没反应”+(事件必须走界面订阅过的那条 Core 连接；另起一条
            // 没订阅的 socket 收不到任何会话进度，手机就只能发出消息、看不到回复)。
            let send = link.sender();
            let flag = Arc::clone(&closed);
            let rpc_for_events = Arc::clone(&rpc);
            let events_thread = Arc::clone(&last_thread);
            tokio::spawn(async move {
                loop {
                    if *flag.lock().await {
                        return;
                    }
                    // 桥重建之后事件流会换一条，外层循环重新订阅它。
                    let bridge = { rpc_for_events.lock().await.clone() };
                    let Some(bridge) = bridge else {
                        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
                        continue;
                    };
                    let mut events = bridge.subscribe_events();
                    loop {
                        if *flag.lock().await {
                            return;
                        }
                        match events.recv().await {
                            Ok(value) => {
                                let Some(method) = value.get("method").and_then(|item| item.as_str()) else {
                                    continue;
                                };
                                let params = value.get("params").cloned().unwrap_or(serde_json::Value::Null);
                                if sunday_p2p::link::write_event(&send, method, params).await.is_err() {
                                    return;
                                }
                            }
                            // user:“一轮里事件比转发快，不能悄悄丢”+(界面靠 thread/gap
                            // 自己重新 resume；这条腿以前直接 continue，手机上就只剩半截内容。)
                            Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {
                                let thread = events_thread
                                    .lock()
                                    .await
                                    .clone()
                                    .unwrap_or_default();
                                let params = serde_json::json!({
                                    "thread_id": thread,
                                    "reason": "p2p_lagged",
                                });
                                if sunday_p2p::link::write_event(&send, "thread/gap", params)
                                    .await
                                    .is_err()
                                {
                                    return;
                                }
                            }
                            // 这条桥没了：回到外层换一条。
                            Err(_) => break,
                        }
                    }
                    tokio::time::sleep(std::time::Duration::from_millis(500)).await;
                }
            });
        } else if core_port != 0 {
            let send = link.sender();
            let flag = Arc::clone(&closed);
            tokio::spawn(sunday_p2p::events::pump_until_closed(core_port, pump_token, send, flag));
        }
        // 处理闭包里也要写日记（桥重建），给它一份自己的目录，别把外层的搬走。
        let handler_dir = log_dir.clone();
        let result = link
            .serve(move |method, params| {
                let name = name.clone();
                let core_token = core_token.clone();
                let rpc = rpc.clone();
                let dir = handler_dir.clone();
                let last_thread = Arc::clone(&last_thread);
                async move {
                    // 记下界面当前订阅的会话：事件丢帧时 thread/gap 要指名这一条。
                    if matches!(method.as_str(), "thread/resume") {
                        if let Some(thread) = params.get("thread_id").and_then(|value| value.as_str()) {
                            *last_thread.lock().await = Some(thread.to_owned());
                        }
                    }
                    match method.as_str() {
                        "ping" => Ok(serde_json::json!({ "pong": true })),
                        "whoami" => Ok(serde_json::json!({ "device": name })),
                        "echo" => Ok(params),
                        // 界面在每条连接上都会先发一次 initialize，重载之后再发一次。
                        // 桥已经替它介绍过自己，这里把同一份答复还回去，而不是让 Core
                        // 以「Already initialized」拒掉界面后面所有 RPC。
                        "initialize" => {
                            let bridge = { rpc.lock().await.clone() };
                            match bridge {
                                Some(bridge) => Ok(bridge.initialize_result()),
                                None => bail!("这台设备没有配置 Core 端口"),
                            }
                        }
                        // 介绍完成的确认通知：Core 那边早就不需要了。
                        "initialized" => Ok(serde_json::json!({})),
                        // 远程的 Core 调用：把 method/path 原样转给本机 Core。
                        "core_http" => {
                            if core_port == 0 {
                                bail!("这台设备没有配置 Core 端口");
                            }
                            let http = params
                                .get("method")
                                .and_then(|value| value.as_str())
                                .unwrap_or("GET")
                                .to_owned();
                            let path = params
                                .get("path")
                                .and_then(|value| value.as_str())
                                .unwrap_or("/")
                                .to_owned();
                            // user:“连上电脑了之后也没有出现项目”+(界面用相对路径 /projects，
                            // 本机通道在宿主里补了 /api/core 前缀，这条远程转发以前没有补，
                            // 于是电脑上每个这样的请求都是 404)。
                            let path = if path.starts_with("/api/") {
                                path
                            } else {
                                format!("/api/core{path}")
                            };
                            // user:“远程模式下附件发不出去、图片预览是坏的”+(以前这条只带
                            // JSON 文本，multipart 和图片字节全被当文本毁掉；现在头与字节原样
                            // 透传，回答也按字节带回去)。
                            let headers: Vec<(String, String)> = params
                                .get("headers")
                                .and_then(|value| value.as_object())
                                .map(|map| {
                                    map.iter()
                                        .filter_map(|(name, value)| {
                                            value
                                                .as_str()
                                                .map(|text| (name.clone(), text.to_owned()))
                                        })
                                        .collect()
                                })
                                .unwrap_or_default();
                            let body = match params.get("body_b64").and_then(|value| value.as_str()) {
                                Some(text) if !text.is_empty() => {
                                    Some(B64.decode(text).context("请求体不是合法的 base64")?)
                                }
                                _ => None,
                            };
                            let token = core_token.clone();
                            // 阻塞的 TCP 读写要离开异步执行器，否则一条大附件会把别的 RPC 卡住。
                            let (status, headers, body) = tokio::task::spawn_blocking(move || {
                                sunday_p2p::proxy::call_core_raw(
                                    "127.0.0.1",
                                    core_port,
                                    &token,
                                    &http,
                                    &path,
                                    &headers,
                                    body,
                                )
                            })
                            .await
                            .context("转发任务没有完成")??;
                            let headers: std::collections::HashMap<String, String> =
                                headers.into_iter().collect();
                            Ok(serde_json::json!({
                                "status": status,
                                "headers": headers,
                                "body_b64": B64.encode(body),
                            }))
                        }
                        // 其余一律当成 Core 的 JSON-RPC 方法原样转过去：
                        // 界面正是靠这条路拿项目、会话与工作台快照。
                        other => {
                            if core_port == 0 {
                                bail!("这台设备没有配置 Core 端口");
                            }
                            let bridge = {
                                let mut guard = rpc.lock().await;
                                let dead = guard.as_ref().map(|item| item.is_dead()).unwrap_or(true);
                                if dead {
                                    match sunday_p2p::rpc::CoreRpc::connect(core_port, &core_token).await {
                                        Ok(fresh) => {
                                            let line = "RPC-CHANNEL REBUILT".to_owned();
                                            println!("{line}");
                                            diary(&dir, &line);
                                            *guard = Some(Arc::new(fresh));
                                        }
                                        Err(error) => {
                                            let line = format!("RPC-CHANNEL REBUILD FAILED {error:#}");
                                            eprintln!("{line}");
                                            diary(&dir, &line);
                                            return Err(anyhow::anyhow!(
                                                "和 Core 的 RPC 通道断了，重建也失败：{error:#}"
                                            ));
                                        }
                                    }
                                }
                                guard.as_ref().expect("bridge just ensured").clone()
                            };
                            bridge.call(other, params).await
                        }
                    }
                }
            })
            .await;
        *closed.lock().await = true;
        match result {
            Ok(()) => {
                println!("PEER-CLOSED {}", link.peer);
                diary(&log_dir, &format!("PEER-CLOSED {}", link.peer));
            }
            Err(error) => {
                println!("PEER-ERROR {} {error:#}", link.peer);
                diary(&log_dir, &format!("PEER-ERROR {} {error:#}", link.peer));
            }
        }
        link.close();
        });
    }
}

async fn call(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.ticket.trim().is_empty() {
        bail!("--ticket is required");
    }
    let identity = Identity::load_or_create(&flags.dir)?;
    let endpoint = identity.endpoint().await?;
    let params: serde_json::Value =
        serde_json::from_str(&flags.params).context("--params must be JSON")?;
    let client = Client::dial(&endpoint, &flags.ticket, &flags.name).await?;
    let result = client.call(&flags.method, params).await?;
    println!("PEER {}", client.peer);
    println!("RESULT {}", serde_json::to_string(&result)?);
    if flags.watch > 0 {
        let mut events = client.subscribe();
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(flags.watch);
        loop {
            let left = deadline.saturating_duration_since(std::time::Instant::now());
            if left.is_zero() {
                break;
            }
            match tokio::time::timeout(left, events.recv()).await {
                Ok(Ok(event)) => println!(
                    "EVENT {} {}",
                    event.method,
                    serde_json::to_string(&event.params)?
                ),
                Ok(Err(_)) => break,
                Err(_) => break,
            }
        }
    }
    client.close();
    endpoint.close().await;
    Ok(())
}
