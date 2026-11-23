//! A tiny driver for the transport.
//!
//! user:“先打通两台设备之间的真实连接与远程会话，再完善设备管理和交互体验”+(这个
//! 命令就是"真实连接"的最小可验证入口：一台服务，一台连上去问一个问题)。

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{bail, Context, Result};
use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use sunday_p2p::pair::{self, PairingGrants};
use sunday_p2p::{Client, Identity, PathKind, ServerLink, StatusEvent, TrustStore};
use tokio::sync::Mutex;

#[tokio::main]
async fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("serve") => serve(args.collect()).await,
        Some("call") => call(args.collect()).await,
        Some("qr") => qr(args.collect()),
        Some("scan") => scan(args.collect()),
        Some("devices") => devices(args.collect()),
        Some("revoke") => revoke(args.collect()),
        Some("watch") => watch(args.collect()).await,
        Some("send") => send(args.collect()).await,
        _ => {
            println!("{}", USAGE);
            Ok(())
        }
    }
}

// user:“验收：打印的 USAGE 里出现 qr 和 scan”+(帮助文本必须列出所有子命令，否则按帮助
// 判断二进制能力会得出"没有二维码功能"的错误结论)。
const USAGE: &str = "sunday-p2p serve --dir <dir> --name <name> [--receive <dir>]\n\
                     sunday-p2p send --dir <dir> --ticket <ticket> --file <path> [--as <filename>]\n\
                     sunday-p2p call --dir <dir> --name <name> --ticket <ticket> [--method ping] [--params '{}']\n\
                     sunday-p2p qr --ticket <ticket>\n\
                     sunday-p2p scan --file <image>\n\
                     sunday-p2p devices --dir <dir>\n\
                     sunday-p2p revoke --dir <dir> --id <device>\n\
                     sunday-p2p watch --dir <dir> --ticket <ticket> [--core-port <port>] [--repeat <seconds>] [--attempts <n>]
                                        [--thread <id>] [--send-key <idempotency-key>] [--send-method ping] [--send-params '{}']";

/// 配对二维码的有效期。
///
/// user:“二维码是短时、一次性的配对授权：有效期明确（建议 ≤5 分钟）”+(过期就必须重新生成，
/// 用户不需要记住任何状态；一次性由 `pair::PairingGrants` 记在盘上)。
const PAIRING_TTL: std::time::Duration = std::time::Duration::from_secs(300);

/// 每条状态既打旧格式（别的脚本还在读），也打一条带版本前缀的结构化行。
///
/// user:“SESSION 依赖解析子进程 stdout 文本（弱契约）→ 改为结构化状态通道”+(宿主以后只
/// 认这一行：字段名固定、带版本号，加字段不会再变成「界面一直显示没连上」)。
fn status(event: StatusEvent) {
    use std::io::Write as _;
    print!("{}", event.render());
    let _ = std::io::stdout().flush();
}

struct Flags {
    dir: PathBuf,
    name: String,
    ticket: String,
    method: String,
    params: String,
    core_port: u16,
    core_token: String,
    watch: u64,
    /// 连上之后每隔一秒再调一次，用来验证撤权对活跃连接当场生效。
    repeat: u64,
    file: String,
    /// `revoke --id` 要移除的设备。
    id: String,
    /// `watch` 最多重连几次。
    attempts: u32,
    /// `watch` 在看哪条会话（重连后按会话查日志）。
    thread: String,
    /// 待发写操作的幂等键；空表示不发。
    send_key: String,
    /// 待发写操作的方法与参数。
    send_method: String,
    send_params: String,
    /// 上次进程里没收到回执的写（重启后连上先查状态）。
    restore_pending: Vec<String>,
    /// 发送时给对端的文件名（空表示沿用本地文件名）。
    ///
    /// 与 `--name` 分开：`--name` 是这台设备的显示名（握手用），`--as` 是文件对端看到的名字。
    as_name: String,
    /// 收到的文件落在哪（空表示用 `<dir>/received`）。
    ///
    /// user:“桌面端收到文件后落盘到约定目录（例如 <lam_home>/received/<日期>/）”+(传输
    /// 进程自己决定不了 lam_home 在哪，宿主用这个参数指过来；不指就落在传输进程自己的
    /// 数据目录下，开发与测试都能直接看到)。
    receive: String,
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
        repeat: 0,
        file: String::new(),
        id: String::new(),
        attempts: 20,
        thread: String::new(),
        send_key: String::new(),
        send_method: "ping".to_owned(),
        send_params: "{}".to_owned(),
        restore_pending: Vec::new(),
        receive: String::new(),
        as_name: String::new(),
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
            "--repeat" => flags.repeat = value()?.parse()?,
            "--file" => flags.file = value()?,
            "--id" => flags.id = value()?,
            "--attempts" => flags.attempts = value()?.parse()?,
            "--thread" => flags.thread = value()?,
            "--send-key" => flags.send_key = value()?,
            "--send-method" => flags.send_method = value()?,
            "--send-params" => flags.send_params = value()?,
            "--restore-pending" => flags.restore_pending.push(value()?),
            "--receive" => flags.receive = value()?,
            "--as" => flags.as_name = value()?,
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
///
/// user:“手机端远控电脑连接不稳定，频繁断连”+(以前没有时间戳，PEER / PEER-CLOSED 只能
/// 看出「很多次」，看不出间隔是 2 秒还是 2 分钟，也就分不清「正在用的时候断」和「切后台
/// 回来重连」；现在每行都带 UTC 时间)。
fn diary(dir: &std::path::Path, line: &str) {
    use std::io::Write;
    let stamp = clock();
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join("p2p.log"))
    {
        let _ = writeln!(file, "{stamp} {line}");
        let _ = file.flush();
    }
}

/// `YYYY-MM-DD HH:MM:SSZ`，只用于读日志，不参与任何判断。
fn clock() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0);
    let days = secs / 86_400;
    let rest = secs % 86_400;
    let (hour, minute, second) = (rest / 3600, (rest % 3600) / 60, rest % 60);
    // 民间日期换算（Howard Hinnant 的 days_from_civil 逆运算），只覆盖 1970 年之后。
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { year + 1 } else { year };
    format!("{year:04}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}Z")
}

async fn serve(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    let identity = Identity::load_or_create(&flags.dir)?;
    let endpoint = identity.endpoint().await?;
    // 出票前等中继就绪，否则票据里只有当时的局域网地址。
    let addr = sunday_p2p::dialable_addr(&endpoint, std::time::Duration::from_secs(10)).await;
    // user:“票据不可伪造（绑定节点身份/公钥）、不可重放到其它设备”+(签名用这台机器的节点
    // 私钥，校验用票据里同一个节点 id 的公钥；票据里还有一次性随机数与过期时间)。
    let ticket = pair::issue(identity.secret(), &addr, PAIRING_TTL, pair::now())?;
    // user:“用过即失效”+(一次性记录和可信名单一样落在自己的目录里，进程重启也记得)。
    let trust = Arc::new(Mutex::new(TrustStore::load(&flags.dir)?));
    let grants = Arc::new(Mutex::new(PairingGrants::load(&flags.dir)?));
    println!("NAME {}", flags.name);
    println!("ID {}", endpoint.id());
    println!("TICKET {}", ticket.text);
    println!("EXPIRES {}", ticket.expires_at);
    status(StatusEvent::Ticket {
        ticket: ticket.text.clone(),
        expires_at: ticket.expires_at,
    });
    // user:“票据就是完整控制权”+(拿到它的人可以调用 Core 的任何 RPC，包括执行工具。
    // 日志会被复制出去排障，所以默认只记前缀；要用日志里的票据做实验时显式开环境变量)。
    let logged_ticket = if std::env::var("SUNDAY_P2P_LOG_TICKET").ok().as_deref() == Some("1") {
        ticket.text.clone()
    } else {
        format!("{}…", &ticket.text[..ticket.text.len().min(24)])
    };
    diary(&flags.dir, &format!("TICKET {logged_ticket}"));
    for line in sunday_p2p::relay_summary(&endpoint) {
        println!("RELAY {line}");
        status(StatusEvent::Relay {
            summary: line.clone(),
        });
        diary(&flags.dir, &format!("RELAY {line}"));
    }
    // 网络切换后地址会变：重新出一张票再打一行，宿主读到就更新二维码。
    // user:“过期后必须重新生成”+(地址变了，旧码里的地址已经连不上；同时把旧码作废，
    // 屏幕上永远只有一张能用的码)。
    {
        let endpoint = endpoint.clone();
        let secret = identity.secret().clone();
        let grants = Arc::clone(&grants);
        let mut current_addr = addr.clone();
        let mut current = (ticket.nonce.clone(), ticket.expires_at);
        tokio::spawn(async move {
            use iroh::Watcher as _;
            let mut watcher = endpoint.watch_addr();
            loop {
                let next_addr = match watcher.updated().await {
                    Ok(addr) => addr,
                    Err(_) => break,
                };
                if next_addr == current_addr {
                    continue;
                }
                let Ok(fresh) = pair::issue(&secret, &next_addr, PAIRING_TTL, pair::now()) else {
                    continue;
                };
                current_addr = next_addr;
                {
                    let mut guard = grants.lock().await;
                    guard.retire(&current.0, current.1);
                    guard.save().ok();
                }
                current = (fresh.nonce.clone(), fresh.expires_at);
                println!("TICKET {}", fresh.text);
                println!("EXPIRES {}", fresh.expires_at);
                status(StatusEvent::Ticket {
                    ticket: fresh.text.clone(),
                    expires_at: fresh.expires_at,
                });
            }
        });
    }
    println!("READY");

    loop {
        // user:“第一次连的时候连上了，后面就没有再连上过”“连上了之后也报错”+(实测传输
        // 进程会在一次握手超时之后直接退出，进程一死，电脑这边就再也接不到任何设备；
        // 一次失败的握手只说明这一次没成，记一笔继续等下一台)。
        let link = match ServerLink::accept(
            &endpoint,
            Arc::clone(&trust),
            Arc::clone(&grants),
            &flags.name,
        )
        .await
        {
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
        let path = link.path();
        println!(
            "PEER {} trusted={} path={}",
            link.peer,
            link.trusted,
            path.as_str()
        );
        diary(
            &flags.dir,
            &format!(
                "PEER {} trusted={} path={}",
                link.peer,
                link.trusted,
                path.as_str()
            ),
        );
        status(StatusEvent::Peer {
            peer: link.peer.clone(),
            name: link.peer_name.clone(),
            trusted: link.trusted,
            path: path.as_str().to_owned(),
        });
        // 打洞可能在握手之后几秒才成功，路径会变：用事件流报变化，不轮询。
        {
            let peer = link.peer.clone();
            let dir = flags.dir.clone();
            let log_dir = dir.clone();
            link.watch_path(move |kind: PathKind| {
                println!("PATH {} path={}", peer, kind.as_str());
                let line = format!("PATH {} path={}", peer, kind.as_str());
                status(StatusEvent::Path {
                    peer: peer.clone(),
                    path: kind.as_str().to_owned(),
                });
                diary(&log_dir, &line);
            });
        }
        if !link.trusted {
            // user:“允许撤销授权”+(被撤销的设备在握手里已经拿到 trusted=false，这里主动收掉，
            // 对端会看到「已被撤销」而不是一句看不懂的 closed by peer)。
            println!("PEER-REJECTED {}", link.peer);
            diary(&flags.dir, &format!("PEER-REJECTED {}", link.peer));
            status(StatusEvent::PeerClosed {
                peer: link.peer.clone(),
                reason: "device_rejected".to_owned(),
            });
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
        // user:“桌面端收到文件后落盘到约定目录（例如 <lam_home>/received/<日期>/）”+
        // (宿主用 `--receive` 指过来；不指就放在传输进程自己的数据目录下)。
        let receive_root = if flags.receive.is_empty() {
            flags.dir.join("received")
        } else {
            PathBuf::from(&flags.receive)
        };
        tokio::spawn(async move {
        let closed = Arc::new(tokio::sync::Mutex::new(false));
        // 最近一次被界面订阅的会话，事件丢帧时用它告诉界面该重新 resume 哪一条。
        let last_thread: Arc<tokio::sync::Mutex<Option<String>>> =
            Arc::new(tokio::sync::Mutex::new(None));
        // user:“事件泵重连不带游标”+(这条事件腿在 Core 重启后也会换一条桥。位点记在
        // 外面：桥重建时把它交给 Core，断掉那几秒的 journal 事件才会被补回来，而不是
        // 让手机从「现在」开始，静默少一段)。
        let cursor: Arc<std::sync::Mutex<sunday_p2p::Cursor>> =
            Arc::new(std::sync::Mutex::new(sunday_p2p::Cursor::default()));
        if rpc.lock().await.is_some() {
            // user:“请立即回复你好没反应”+(事件必须走界面订阅过的那条 Core 连接；另起一条
            // 没订阅的 socket 收不到任何会话进度，手机就只能发出消息、看不到回复)。
            let send = link.sender();
            let flag = Arc::clone(&closed);
            let rpc_for_events = Arc::clone(&rpc);
            let events_thread = Arc::clone(&last_thread);
            let cursor_for_events = Arc::clone(&cursor);
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
                                // 先记位点再转发：这一条转发失败，下一次重连还能补回来。
                                if let Ok(mut cursor) = cursor_for_events.lock() {
                                    cursor.observe(&params);
                                }
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
        // serve 接管了连接的读半边，连接本身也随它结束；对端 id 先留一份给日志。
        let peer = link.peer.clone();
        // user:“只有业务真正可用才显示「已连接电脑」”+(真的完成 initialize 才说明
        // 手机能读写会话；宿主只认这一行证据，不再靠「有设备 + Core 通」猜)。
        let session_peer = peer.clone();
        // user:“发送与接收都要有可观察进度（百分比或已传字节）”+(进度走既有的 event 帧，
        // 不新开一条通道；同时打一行结构化状态给宿主，界面不必解析中文)。
        let progress_send = link.sender();
        let progress_dir = log_dir.clone();
        let progress_peer = peer.clone();
        let progress_from = link.peer_name.clone();
        let trusted_peer = link.trusted;
        let sink: sunday_p2p::transfer::ProgressSink =
            Arc::new(move |progress: sunday_p2p::transfer::Progress| {
                println!(
                    "TRANSFER {} {} {}% {}/{}",
                    progress.direction,
                    progress.name,
                    progress.percent,
                    progress.transferred,
                    progress.total
                );
                status(StatusEvent::Transfer {
                    transfer_id: progress.transfer_id.clone(),
                    direction: progress.direction.clone(),
                    name: progress.name.clone(),
                    total: progress.total,
                    transferred: progress.transferred,
                    percent: progress.percent,
                    state: progress.state.clone(),
                    code: progress.code.clone(),
                    message: progress.message.clone(),
                    path: progress.path.clone(),
                });
                let body = serde_json::to_value(&progress).unwrap_or(serde_json::Value::Null);
                let send = Arc::clone(&progress_send);
                tokio::spawn(async move {
                    let _ = sunday_p2p::link::write_event(
                        &send,
                        sunday_p2p::transfer::PROGRESS_EVENT,
                        body,
                    )
                    .await;
                });
                // user:“收到文件后落盘、登记为 artifact 条目、给出打开预览/所在文件夹的入口”+
                // (宿主只认 `received` 这一条来登记资料库：它带绝对路径与来源设备)。
                if progress.direction == "receive"
                    && progress.state == "completed"
                    && !progress.path.is_empty()
                {
                    println!("RECEIVED {} {}", progress.name, progress.path);
                    status(StatusEvent::Received {
                        transfer_id: progress.transfer_id.clone(),
                        path: progress.path.clone(),
                        name: progress.name.clone(),
                        size: progress.total,
                        peer: progress_peer.clone(),
                        from: progress_from.clone(),
                    });
                    diary(
                        &progress_dir,
                        &format!(
                            "RECEIVED {} {} {}",
                            progress.name, progress.total, progress.path
                        ),
                    );
                }
            });
        let receiver = Arc::new(sunday_p2p::transfer::Receiver::new(
            receive_root,
            trusted_peer,
            sink,
        ));
        let result = link
            .serve(move |method, params| {
                let name = name.clone();
                let core_token = core_token.clone();
                let rpc = rpc.clone();
                let dir = handler_dir.clone();
                let session_peer = session_peer.clone();
                let last_thread = Arc::clone(&last_thread);
                let cursor = Arc::clone(&cursor);
                let receiver = Arc::clone(&receiver);
                async move {
                    // user:“只允许已信任设备互传”+(这条连接在 `serve` 里每条调用前都已经复核
                    // 撤权；`Receiver` 再按握手结论兜一道，未授权时连 offer 都不落盘——拒绝
                    // 必须发生在写盘之前，否则「被拒绝」也已经在用户目录里留下痕迹)。
                    if sunday_p2p::transfer::is_transfer_method(&method) {
                        return match receiver.handle(&method, &params) {
                            Ok(result) => Ok(result),
                            Err(error) => Err(sunday_p2p::transfer::as_anyhow(error)),
                        };
                    }
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
                                Some(bridge) => {
                                    // user:“只有业务真正可用才显示「已连接电脑」”+(这条连接
                                    // 真的完成 initialize 才说明手机那边已经能读写会话)。
                                    println!("SESSION {}", session_peer);
                                    diary(&dir, &format!("SESSION {session_peer}"));
                                    status(StatusEvent::Session {
                                        peer: session_peer.clone(),
                                    });
                                    Ok(bridge.initialize_result())
                                }
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
                                    // user:“事件泵重连不带游标”+(重建这条桥时把位点带上：
                                    // Core 会从漏掉的地方续订，而不是从「现在」开始)。
                                    let (last_seq, thread) = cursor
                                        .lock()
                                        .map(|cursor| {
                                            (cursor.seq(), cursor.thread().map(|thread| thread.to_owned()))
                                        })
                                        .unwrap_or((0, None));
                                    match sunday_p2p::rpc::CoreRpc::connect_from(
                                        core_port,
                                        &core_token,
                                        last_seq,
                                        thread.as_deref(),
                                    )
                                    .await
                                    {
                                        Ok(fresh) => {
                                            let line = format!(
                                                "RPC-CHANNEL REBUILT last_seen_seq={last_seq}"
                                            );
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
                println!("PEER-CLOSED {}", peer);
                diary(&log_dir, &format!("PEER-CLOSED {}", peer));
                status(StatusEvent::PeerClosed {
                    peer: peer.clone(),
                    reason: String::new(),
                });
            }
            Err(error) => {
                println!("PEER-ERROR {} {error:#}", peer);
                diary(&log_dir, &format!("PEER-ERROR {} {error:#}", peer));
                status(StatusEvent::PeerClosed {
                    peer: peer.clone(),
                    reason: error.to_string(),
                });
            }
        }
        });
    }
}

/// 列出可信与被撤销的设备（和桌面宿主读的是同一份 `p2p-trust.json`）。
fn devices(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    let store = TrustStore::load(&flags.dir)?;
    for device in &store.devices {
        println!("DEVICE {} {}", device.id, device.name);
    }
    for device in &store.revoked {
        println!("REVOKED {} {}", device.id, device.name);
    }
    Ok(())
}

/// 撤销一台设备。
///
/// user:“用户移除设备后，当前已建立的连接立刻失去操作权限”+(写的还是那份名单文件；
/// 正在跑的那条连接每次调用前都会按文件时间戳重读，所以撤销对活跃连接是当场生效)。
fn revoke(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.id.trim().is_empty() {
        bail!("--id is required");
    }
    let mut store = TrustStore::load(&flags.dir)?;
    // 先看一眼宿主有没有刚写过，别把自己的旧副本盖回去。
    store.reload_if_stale().ok();
    let changed = store.revoke(flags.id.trim());
    store.save()?;
    println!(
        "REVOKED {} {}",
        flags.id.trim(),
        if changed { "yes" } else { "no" }
    );
    Ok(())
}

/// 看护这条连接：断线自动重连、Core 挂了当场降级。
///
/// user:“智能自动恢复/消除假在线”+(实现全在 `sunday_p2p::watch`，宿主与脚本共用一份；
/// 这里只负责把命令行参数交过去)。
async fn watch(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.ticket.trim().is_empty() {
        bail!("--ticket is required");
    }
    let identity = Identity::load_or_create(&flags.dir)?;
    let endpoint = identity.endpoint().await?;
    let mut options = sunday_p2p::watch::WatchOptions::new(&flags.ticket, &flags.name);
    options.core_port = flags.core_port;
    // user:“不确定送达时先查询状态，不盲目重发”+(看护这条连接的是宿主，账本也在它手里：
    // 给了会话就按会话查日志，给了键就在每次连上之后先查再谈重发)。
    if !flags.thread.trim().is_empty() {
        options.thread = Some(flags.thread.trim().to_owned());
    }
    if !flags.send_key.trim().is_empty() {
        let params: serde_json::Value =
            serde_json::from_str(&flags.send_params).context("--send-params must be JSON")?;
        options.send = Some(sunday_p2p::PendingSend {
            key: flags.send_key.trim().to_owned(),
            method: flags.send_method.clone(),
            params,
        });
    }
    // user:“不确定送达时先查询状态，不盲目重发”+(宿主重启后把悬着的写交回来，先查再谈重发)。
    options.restore = flags.restore_pending.clone();
    options.total = std::time::Duration::from_secs(flags.repeat.max(60));
    options.attempts = flags.attempts.max(1);
    let result = sunday_p2p::watch::run(&endpoint, options).await;
    endpoint.close().await;
    result
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
    // 给脚本一个稳定的 ASCII 标记，中文原因接在后面给。人看的还是那句话。
    let client = match Client::dial(&endpoint, &flags.ticket, &flags.name).await {
        Ok(client) => client,
        Err(error) => {
            println!("DIAL FAILED {error:#}");
            return Err(error);
        }
    };
    let result = client.call(&flags.method, params).await?;
    println!("PEER {}", client.peer);
    println!("RESULT {}", serde_json::to_string(&result)?);
    // user:“已授权设备后续能自动重连，不要求每次重新扫”+(把地址票存起来，
    // 下次拿它直连；它只说明往哪连，授权仍然由可信名单判定)。
    println!("RESUME {}", client.resume_ticket()?);
    // user:“用户移除设备后，当前已建立的连接立刻失去操作权限”+(脚本验收用：连上之后每隔一秒发一次真实调用，撤销后应当当场拿到
    // `device_revoked`，而不是继续成功)。
    if flags.repeat > 0 {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(flags.repeat);
        while std::time::Instant::now() < deadline {
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
            match client.call("ping", serde_json::json!({})).await {
                Ok(value) => println!("REPEAT OK {}", serde_json::to_string(&value)?),
                Err(error) => {
                    println!("REPEAT FAIL {error:#}");
                    break;
                }
            }
        }
    }
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

/// user:“发送：在文件树/资料库/预览器里对某个文件「发送到设备」→ 选择已信任设备 → 走 p2p
/// 传过去；大文件分块、可取消、有进度”+(拨号方负责发、接收方负责落盘，两端共用同一份
/// `transfer` 实现；桌面宿主与手机宿主将来都走这一条入口，不各写一套)。
async fn send(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.ticket.trim().is_empty() {
        bail!("--ticket is required");
    }
    if flags.file.trim().is_empty() {
        bail!("--file is required");
    }
    let path = PathBuf::from(flags.file.trim());
    let identity = Identity::load_or_create(&flags.dir)?;
    let endpoint = identity.endpoint().await?;
    let client = match Client::dial(&endpoint, &flags.ticket, &flags.name).await {
        Ok(client) => client,
        Err(error) => {
            // 给脚本一个稳定的 ASCII 标记；原因照旧打出来给人看。
            println!("DIAL FAILED {error:#}");
            endpoint.close().await;
            return Err(error);
        }
    };
    println!("PEER {}", client.peer);
    // 进度打两行：一行给人看，一行是宿主与脚本认的结构化状态。
    let sink: sunday_p2p::transfer::ProgressSink =
        Arc::new(|progress: sunday_p2p::transfer::Progress| {
            println!(
                "TRANSFER {} {} {}% {}/{}",
                progress.direction,
                progress.name,
                progress.percent,
                progress.transferred,
                progress.total
            );
            status(StatusEvent::Transfer {
                transfer_id: progress.transfer_id.clone(),
                direction: progress.direction.clone(),
                name: progress.name.clone(),
                total: progress.total,
                transferred: progress.transferred,
                percent: progress.percent,
                state: progress.state.clone(),
                code: progress.code.clone(),
                message: progress.message.clone(),
                path: progress.path.clone(),
            });
        });
    let client = Arc::new(client);
    let caller = Arc::clone(&client);
    // 互传只认「一次调用」这件事：谁提供它都行（宿主以后用 ask 帧或自己的桥都可以）。
    let call = move |method: String, params: serde_json::Value| {
        let client = Arc::clone(&caller);
        async move { client.call(&method, params).await }
    };
    let as_name = if flags.as_name.trim().is_empty() {
        None
    } else {
        Some(flags.as_name.trim())
    };
    let result = sunday_p2p::transfer::send_file(call, &path, as_name, &sink).await;
    let resume = client.resume_ticket().ok();
    client.close();
    endpoint.close().await;
    match result {
        Ok(sent) => {
            println!(
                "SENT name={} bytes={} chunks={} path={}",
                sent.name, sent.bytes, sent.chunks, sent.remote_path
            );
            if let Some(ticket) = resume {
                println!("RESUME {ticket}");
            }
            Ok(())
        }
        Err(error) => {
            println!("SEND FAILED {error}");
            bail!("{error}")
        }
    }
}
