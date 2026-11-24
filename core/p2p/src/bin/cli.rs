//! A tiny driver for the transport.
//!
//! user:“先打通两台设备之间的真实连接与远程会话，再完善设备管理和交互体验”+(这个
//! 命令就是"真实连接"的最小可验证入口：一台服务，一台连上去问一个问题)。

use std::io::BufRead;
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
        Some("pending") => pending(args.collect()),
        Some("confirm") => confirm(args.collect()),
        Some("reject") => reject(args.collect()),
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
    transfer_id: Option<String>,
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
        transfer_id: None,
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
            "--transfer-id" => flags.transfer_id = Some(value()?),
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

fn read_desktop_commands(
    input: impl BufRead,
    renew: tokio::sync::mpsc::Sender<()>,
    cancel: Option<tokio::sync::mpsc::Sender<String>>,
) {
    for line in input.lines().map_while(Result::ok) {
        if line == "renew-ticket" {
            let _ = renew.try_send(());
        } else if let (Some(value), Some(cancel)) = (line.strip_prefix("cancel-receive "), &cancel)
        {
            if let Ok(id) = serde_json::from_str::<String>(value) {
                let _ = cancel.blocking_send(id);
            }
        }
    }
}

#[cfg(test)]
#[test]
fn only_renew_commands_request_a_new_pairing_code() {
    // user:“三项全做”+(桌面的重新生成请求进入运行中的传输进程，其他输入不触发换码)。
    let (send, mut receive) = tokio::sync::mpsc::channel(2);
    read_desktop_commands(&b"other\r\nrenew-ticket\r\n"[..], send, None);
    assert_eq!(receive.try_recv(), Ok(()));
    assert_eq!(
        receive.try_recv(),
        Err(tokio::sync::mpsc::error::TryRecvError::Disconnected)
    );
}

#[test]
fn remote_repair_desktop_cancel_command_preserves_the_transfer_id() {
    let (renew, _renew_requests) = tokio::sync::mpsc::channel(1);
    let (cancel, mut requests) = tokio::sync::mpsc::channel(2);
    read_desktop_commands(
        &b"cancel-receive broken\ncancel-receive \"original-id\"\n"[..],
        renew,
        Some(cancel),
    );
    assert_eq!(requests.try_recv().unwrap(), "original-id");
    assert!(requests.try_recv().is_err());
}

async fn serve(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    let identity = Identity::load_or_create(&flags.dir)?;
    let startup = tokio::time::timeout(std::time::Duration::from_secs(15), identity.endpoint())
        .await
        .context("传输端点初始化超时，请检查本机网络")
        .and_then(std::convert::identity);
    let endpoint = match startup {
        Ok(endpoint) => endpoint,
        Err(error) => {
            status(StatusEvent::StartupFailed { message: error.to_string() });
            return Err(error);
        }
    };
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
    let receive_transfers = sunday_p2p::transfer::ReceiveTransfers::default();
    let (cancel, mut cancel_requests) = tokio::sync::mpsc::channel::<String>(32);
    let cancellations = receive_transfers.clone();
    tokio::spawn(async move {
        while let Some(id) = cancel_requests.recv().await {
            let _ = cancellations.cancel_receiving(&id);
        }
    });
    // user:“三项全做”+(网络地址变化或用户点重新生成时使用同一套换码逻辑，保留在线连接)。
    {
        let endpoint = endpoint.clone();
        let secret = identity.secret().clone();
        let grants = Arc::clone(&grants);
        let mut current_addr = addr.clone();
        let mut current = (ticket.nonce.clone(), ticket.expires_at);
        let (renew, mut renew_requests) = tokio::sync::mpsc::channel(1);
        std::thread::spawn(move || read_desktop_commands(std::io::stdin().lock(), renew, Some(cancel)));
        tokio::spawn(async move {
            use iroh::Watcher as _;
            let mut watcher = endpoint.watch_addr();
            loop {
                let (next_addr, manual) = tokio::select! {
                    result = watcher.updated() => match result {
                        Ok(addr) if addr == current_addr => continue,
                        Ok(addr) => (addr, false),
                        Err(_) => break,
                    },
                    Some(()) = renew_requests.recv() => (endpoint.addr(), true),
                };
                let Ok(fresh) = pair::issue(&secret, &next_addr, PAIRING_TTL, pair::now()) else {
                    continue;
                };
                {
                    let mut guard = grants.lock().await;
                    if let Err(error) = guard.reload_if_stale() {
                        eprintln!("[sunday-p2p] cannot reload pairing state before rotating: {error}");
                        continue;
                    }
                    let mut updated = guard.clone();
                    if manual {
                        updated.retire(&current.0, current.1);
                    } else {
                        updated.retire_after_address_change(&current.0, current.1);
                    }
                    if let Err(error) = updated.save() {
                        eprintln!("[sunday-p2p] cannot persist pairing rotation: {error}");
                        continue;
                    }
                    *guard = updated;
                }
                current_addr = next_addr;
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

    let sweep_transfers = receive_transfers.clone();
    tokio::spawn(async move {
        let mut sweep = tokio::time::interval(std::time::Duration::from_secs(30));
        loop {
            sweep.tick().await;
            sweep_transfers.sweep_stale();
        }
    });
    let flags = Arc::new(flags);
    let handshake_slots = Arc::new(tokio::sync::Semaphore::new(16));
    let peer_events = Arc::new(std::sync::Mutex::new(std::collections::HashMap::new()));
    loop {
        let permit = Arc::clone(&handshake_slots).acquire_owned().await?;
        let Some(incoming) = endpoint.accept().await else { return Ok(()) };
        let endpoint = endpoint.clone();
        let flags = Arc::clone(&flags);
        let trust = Arc::clone(&trust);
        let grants = Arc::clone(&grants);
        let transfers = receive_transfers.clone();
        let peer_events = Arc::clone(&peer_events);
        tokio::spawn(async move {
            let handshake = ServerLink::handshake(&endpoint, incoming, trust, grants, &flags.name);
            match finish_handshake(permit, std::time::Duration::from_secs(12), handshake).await {
                Ok(link) => serve_peer(link, flags, transfers, peer_events).await,
                Err(error) => {
                    let line = format!("ACCEPT ERROR {error:#}");
                    eprintln!("{line}");
                    diary(&flags.dir, &line);
                }
            }
        });
    }
}

// user:“全修”+(慢握手有截止时间，连接一旦完成握手便释放并发名额)。
async fn finish_handshake<T>(
    permit: tokio::sync::OwnedSemaphorePermit,
    timeout: std::time::Duration,
    handshake: impl std::future::Future<Output = Result<T>>,
) -> Result<T> {
    let result = tokio::time::timeout(timeout, handshake).await;
    drop(permit);
    result.context("设备握手超时")?
}

#[tokio::test]
async fn remote_repair_slow_handshake_does_not_block_another_device() {
    use std::time::Duration;
    let slots = Arc::new(tokio::sync::Semaphore::new(2));
    let slow = Arc::clone(&slots).acquire_owned().await.unwrap();
    let fast = Arc::clone(&slots).acquire_owned().await.unwrap();
    let slow = tokio::spawn(finish_handshake(
        slow,
        Duration::from_millis(60),
        std::future::pending::<Result<()>>(),
    ));
    assert_eq!(
        finish_handshake(fast, Duration::from_secs(1), async { Ok(42) })
            .await
            .unwrap(),
        42
    );
    assert!(slow.await.unwrap().is_err());
    assert_eq!(slots.available_permits(), 2);
}

type ThreadState = Arc<std::sync::Mutex<sunday_p2p::events::ThreadCursors>>;
type PeerEvents = Arc<std::sync::Mutex<std::collections::HashMap<String, ThreadState>>>;
type CoreBridge = Arc<Mutex<Option<Arc<sunday_p2p::rpc::CoreRpc>>>>;

fn remember_thread(cursor: &ThreadState, params: &serde_json::Value, recover: bool) {
    let Some(thread) = params
        .get("thread_id")
        .or_else(|| params.get("threadId"))
        .and_then(|value| value.as_str())
    else {
        return;
    };
    let seq = params
        .get("last_seen_seq")
        .or_else(|| params.get("lastSeenSeq"))
        .and_then(|value| value.as_u64());
    let mut cursor = cursor.lock().unwrap_or_else(|error| error.into_inner());
    if recover && seq.is_some() {
        cursor.rewind(thread, seq.unwrap_or_default());
    } else {
        cursor.track(thread, seq.unwrap_or_default());
    }
}

async fn ensure_core_bridge(
    rpc: &CoreBridge,
    cursor: &ThreadState,
    core_port: u16,
    token: &str,
) -> Result<Arc<sunday_p2p::rpc::CoreRpc>> {
    if core_port == 0 {
        bail!("这台设备没有配置 Core 端口");
    }
    let mut current = rpc.lock().await;
    if let Some(bridge) = current.as_ref().filter(|bridge| !bridge.is_dead()) {
        return Ok(bridge.clone());
    }
    let thread = cursor
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .active()
        .map(str::to_owned);
    let bridge = tokio::time::timeout(
        std::time::Duration::from_secs(12),
        sunday_p2p::rpc::CoreRpc::connect_from(core_port, token, 0, thread.as_deref()),
    )
    .await
    .context("Core 握手超时")??;
    let bridge = Arc::new(bridge);
    *current = Some(bridge.clone());
    Ok(bridge)
}

// user:“全修”+(新连接和 Core 通道重建时逐会话补齐日志，发送成功后才更新位点)。
async fn forward_core_events(
    send: Arc<Mutex<iroh::endpoint::SendStream>>,
    closed: Arc<Mutex<bool>>,
    rpc: CoreBridge,
    cursor: ThreadState,
    mut ready: tokio::sync::watch::Receiver<bool>,
    port: u16,
    token: String,
) {
    use std::time::Duration;
    let tick = Duration::from_millis(500);
    while !*ready.borrow_and_update() {
        if ready.changed().await.is_err() {
            return;
        }
    }
    while !*closed.lock().await {
        let bridge = match ensure_core_bridge(&rpc, &cursor, port, &token).await {
            Ok(bridge) => bridge,
            Err(_) => {
                tokio::time::sleep(tick).await;
                continue;
            }
        };
        let mut events = bridge.subscribe_events();
        loop {
            let positions = cursor
                .lock()
                .unwrap_or_else(|error| error.into_inner())
                .positions();
            let mut retry_replay = false;
            // Core 的每个 WebSocket 只订阅一条会话。用独立的连接回放，避免把当前会话切走。
            let replay = if positions.is_empty() {
                None
            } else {
                match tokio::time::timeout(
                    Duration::from_secs(12),
                    sunday_p2p::rpc::CoreRpc::connect(port, &token),
                )
                .await
                {
                    Ok(Ok(replay)) => Some(replay),
                    _ => {
                        tokio::time::sleep(tick).await;
                        break;
                    }
                }
            };
            for (thread, seq) in positions {
                if *closed.lock().await {
                    return;
                }
                let replay = replay.as_ref().expect("positions require a replay bridge");
                let result = sunday_p2p::events::replay_thread(
                    &thread,
                    seq,
                    |query| replay.call("thread/resume", query),
                    |event| async {
                        let method = event
                            .get("method")
                            .and_then(|value| value.as_str())
                            .unwrap_or("core/event")
                            .to_owned();
                        forward_core_event(&send, &cursor, &method, event).await
                    },
                )
                .await;
                if let Err(error) = result {
                    if error.is::<EventWriteFailed>() {
                        return;
                    }
                    if error.to_string() != "thread not found" {
                        retry_replay = true;
                    }
                }
            }
            if retry_replay {
                tokio::time::sleep(tick).await;
                break;
            }
            drop(replay);
            loop {
                if *closed.lock().await {
                    return;
                }
                if bridge.is_dead() {
                    break;
                }
                match tokio::time::timeout(tick, events.recv()).await {
                    Err(_) => continue,
                    Ok(Err(tokio::sync::broadcast::error::RecvError::Lagged(_))) => break,
                    Ok(Err(tokio::sync::broadcast::error::RecvError::Closed)) => break,
                    Ok(Ok(event)) => {
                        let Some(method) = event.get("method").and_then(|value| value.as_str())
                        else {
                            continue;
                        };
                        let params = event["params"].clone();
                        if forward_core_event(&send, &cursor, method, params)
                            .await
                            .is_err()
                        {
                            return;
                        }
                    }
                }
            }
            if bridge.is_dead() {
                break;
            }
        }
    }
}

#[derive(Debug)]
struct EventWriteFailed;
impl std::fmt::Display for EventWriteFailed {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("无法转发 Core 事件")
    }
}
impl std::error::Error for EventWriteFailed {}

async fn forward_core_event(
    send: &Arc<Mutex<iroh::endpoint::SendStream>>,
    cursor: &ThreadState,
    method: &str,
    params: serde_json::Value,
) -> Result<()> {
    if cursor
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .already_delivered(&params)
    {
        return Ok(());
    }
    if !matches!(
        tokio::time::timeout(
            std::time::Duration::from_secs(30),
            sunday_p2p::link::write_event(send, method, params.clone()),
        )
        .await,
        Ok(Ok(()))
    ) {
        let _ = send.lock().await.reset(0u32.into());
        return Err(EventWriteFailed.into());
    }
    cursor
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .delivered(&params);
    Ok(())
}

async fn serve_peer(
    link: ServerLink,
    flags: Arc<Flags>,
    receive_transfers: sunday_p2p::transfer::ReceiveTransfers,
    peer_events: PeerEvents,
) {
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
        link.watch_path(move |kind: PathKind, rtt_ms: u64| {
            println!("PATH {} path={} rtt={}ms", peer, kind.as_str(), rtt_ms);
            let line = format!("PATH {} path={} rtt={}ms", peer, kind.as_str(), rtt_ms);
            status(StatusEvent::Path {
                peer: peer.clone(),
                path: kind.as_str().to_owned(),
                rtt_ms,
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
        return;
    }
    // 每来一台设备就起一条事件泵：Core 的通知按帧推回给对端。
    let log_dir = flags.dir.clone();
    let name = flags.name.clone();
    let core_port = flags.core_port;
    let core_token = flags.core_token.clone();
    let rpc = Arc::new(Mutex::new(None));
    // user:“桌面端收到文件后落盘到约定目录（例如 <lam_home>/received/<日期>/）”+
    // (宿主用 `--receive` 指过来；不指就放在传输进程自己的数据目录下)。
    let receive_root = if flags.receive.is_empty() {
        flags.dir.join("received")
    } else {
        PathBuf::from(&flags.receive)
    };
    let closed = Arc::new(Mutex::new(false));
    let cursor = peer_events.lock().unwrap_or_else(|error| error.into_inner())
        .entry(link.peer.clone()).or_default().clone();
    let (ready, initialized) = tokio::sync::watch::channel(false);
    if core_port != 0 {
        tokio::spawn(forward_core_events(
            link.sender(), closed.clone(), rpc.clone(), cursor.clone(),
            initialized, core_port, core_token.clone(),
        ));
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
    let receiver = Arc::new(sunday_p2p::transfer::Receiver::for_peer(
        receive_root,
        trusted_peer,
        sink,
        receive_transfers,
        peer.clone(),
    ));
    let result = link
        .serve(move |method, params| {
            let name = name.clone();
            let core_token = core_token.clone();
            let rpc = rpc.clone();
            let dir = handler_dir.clone();
            let session_peer = session_peer.clone();
            let ready = ready.clone();
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
                match method.as_str() {
                    "ping" => Ok(serde_json::json!({ "pong": true })),
                    "whoami" => Ok(serde_json::json!({ "device": name })),
                    "echo" => Ok(params),
                    // 界面在每条连接上都会先发一次 initialize，重载之后再发一次。
                    // 桥已经替它介绍过自己，这里把同一份答复还回去，而不是让 Core
                    // 以「Already initialized」拒掉界面后面所有 RPC。
                    "initialize" => {
                        remember_thread(&cursor, &params, !*ready.borrow());
                        let bridge = ensure_core_bridge(&rpc, &cursor, core_port, &core_token).await?;
                        ready.send_replace(true);
                        println!("SESSION {}", session_peer);
                        diary(&dir, &format!("SESSION {session_peer}"));
                        status(StatusEvent::Session { peer: session_peer.clone() });
                        Ok(bridge.initialize_result())
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
                        remember_thread(&cursor, &params, false);
                        let bridge = ensure_core_bridge(&rpc, &cursor, core_port, &core_token).await?;
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

/// 列出等待电脑确认的配对申请。
///
/// user:“电脑显示待确认设备，用户确认配对”+(扫码只登记申请；这里把申请摆给宿主/人看)。
fn pending(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    let grants = PairingGrants::load(&flags.dir)?;
    for device in grants.pending_devices() {
        println!("PENDING {} {} {}", device.id, device.name, device.expires_at);
    }
    Ok(())
}

/// 电脑确认一台待确认设备：写可信名单并消费这张票。
fn confirm(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.id.trim().is_empty() {
        bail!("--id is required");
    }
    let mut store = TrustStore::load(&flags.dir)?;
    store.reload_if_stale().ok();
    let mut grants = PairingGrants::load(&flags.dir)?;
    grants.reload_if_stale().ok();
    let Some(device) = grants.confirm(flags.id.trim()) else {
        println!("PENDING NOT FOUND {}", flags.id.trim());
        return Ok(());
    };
    store.allow(&device.id);
    store.trust(&device.id, &device.name);
    store.save()?;
    grants.save()?;
    println!("CONFIRMED {} {}", device.id, device.name);
    Ok(())
}

/// 电脑拒绝一台待确认设备：票作废，设备进入撤销名单。
fn reject(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    if flags.id.trim().is_empty() {
        bail!("--id is required");
    }
    let mut store = TrustStore::load(&flags.dir)?;
    store.reload_if_stale().ok();
    let mut grants = PairingGrants::load(&flags.dir)?;
    grants.reload_if_stale().ok();
    let Some(device) = grants.reject(flags.id.trim()) else {
        println!("PENDING NOT FOUND {}", flags.id.trim());
        return Ok(());
    };
    store.revoke(&device.id);
    store.save()?;
    grants.save()?;
    println!("REJECTED {} {}", device.id, device.name);
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
    let resume = client.resume_ticket()?;
    let clients = Arc::new(Mutex::new(Some(client)));
    let caller = Arc::clone(&clients);
    let send_endpoint = endpoint.clone();
    let send_name = flags.name.clone();
    // 互传只认「一次调用」这件事：谁提供它都行（宿主以后用 ask 帧或自己的桥都可以）。
    let call = move |method: String, params: serde_json::Value| {
        let caller = Arc::clone(&caller);
        let endpoint = send_endpoint.clone();
        let ticket = resume.clone();
        let name = send_name.clone();
        async move {
            use sunday_p2p::transfer::InterruptedCall;
            let mut current = caller.lock().await;
            if current.is_none() {
                let retry = tokio::time::timeout(std::time::Duration::from_secs(12), Client::dial(&endpoint, &ticket, &name))
                    .await.map_err(|error| InterruptedCall(error.into()))?
                    .map_err(InterruptedCall)?;
                *current = Some(retry);
            }
            let client = current.as_ref().expect("transfer connection was established");
            let id = params.get("id").and_then(|value| value.as_str()).unwrap_or("").to_owned();
            let mut events = client.subscribe();
            let response = tokio::select! {
                biased;
                _ = wait_for_receiver_cancel(&mut events, &id) => {
                    client.close();
                    return Err(anyhow::anyhow!("[file_cancelled] 接收方取消了传输"));
                }
                result = tokio::time::timeout(std::time::Duration::from_secs(25), client.call(&method, params)) => result,
            };
            let result = match response {
                Ok(Ok(value)) => return Ok(value),
                Ok(Err(error)) if client.is_alive() => return Err(error),
                Ok(Err(error)) => error,
                Err(error) => error.into(),
            };
            if let Some(client) = current.take() { client.close(); }
            Err(InterruptedCall(result).into())
        }
    };
    let as_name = if flags.as_name.trim().is_empty() {
        None
    } else {
        Some(flags.as_name.trim())
    };
    let result = sunday_p2p::transfer::send_file_with_id(call, &path, as_name, flags.transfer_id.as_deref(), &sink).await;
    let current = clients.lock().await.take();
    let resume = current.as_ref().and_then(|client| client.resume_ticket().ok());
    if let Some(client) = current { client.close(); }
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
        Err(error) if error.code() == sunday_p2p::transfer::CODE_CANCELLED => {
            println!("SEND CANCELLED {error}");
            Ok(())
        }
        Err(error) => {
            println!("SEND FAILED {error}");
            bail!("{error}")
        }
    }
}

async fn wait_for_receiver_cancel(
    events: &mut tokio::sync::broadcast::Receiver<sunday_p2p::link::Event>,
    id: &str,
) {
    loop {
        match events.recv().await {
            Ok(event)
                if event.method == sunday_p2p::transfer::PROGRESS_EVENT
                    && event.params["transfer_id"].as_str() == Some(id)
                    && event.params["state"] == "cancelled" =>
            {
                return
            }
            Ok(_) | Err(tokio::sync::broadcast::error::RecvError::Lagged(_)) => {}
            Err(tokio::sync::broadcast::error::RecvError::Closed) => {
                std::future::pending::<()>().await
            }
        }
    }
}

#[tokio::test]
async fn remote_repair_receiver_cancel_notice_matches_only_the_current_transfer() {
    use sunday_p2p::link::Event;
    let (send, mut events) = tokio::sync::broadcast::channel(4);
    send.send(Event {
        method: sunday_p2p::transfer::PROGRESS_EVENT.into(),
        params: serde_json::json!({"transfer_id":"other","state":"cancelled"}),
    })
    .unwrap();
    let mut notice = std::pin::pin!(wait_for_receiver_cancel(&mut events, "active"));
    assert!(futures_util::poll!(&mut notice).is_pending());
    send.send(Event {
        method: sunday_p2p::transfer::PROGRESS_EVENT.into(),
        params: serde_json::json!({"transfer_id":"active","state":"cancelled"}),
    })
    .unwrap();
    notice.await;
}
