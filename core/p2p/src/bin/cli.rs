//! A tiny driver for the transport.
//!
//! user:“先打通两台设备之间的真实连接与远程会话，再完善设备管理和交互体验”+(这个
//! 命令就是"真实连接"的最小可验证入口：一台服务，一台连上去问一个问题)。

use std::path::PathBuf;
use std::sync::Arc;

use anyhow::{bail, Context, Result};
use sunday_p2p::{encode_ticket, Client, Identity, ServerLink, TrustStore};
use tokio::sync::Mutex;

#[tokio::main]
async fn main() -> Result<()> {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("serve") => serve(args.collect()).await,
        Some("call") => call(args.collect()).await,
        Some("qr") => qr(args.collect()),
        _ => {
            println!("{}", USAGE);
            Ok(())
        }
    }
}

const USAGE: &str = "sunday-p2p serve --dir <dir> --name <name>\n\
                     sunday-p2p call --dir <dir> --name <name> --ticket <ticket> [--method ping] [--params '{}']";

struct Flags {
    dir: PathBuf,
    name: String,
    ticket: String,
    method: String,
    params: String,
    core_port: u16,
    core_token: String,
    watch: u64,
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
async fn serve(args: Vec<String>) -> Result<()> {
    let flags = parse(args)?;
    let identity = Identity::load_or_create(&flags.dir)?;
    let endpoint = identity.endpoint().await?;
    let ticket = encode_ticket(&endpoint.addr())?;
    let trust = Arc::new(Mutex::new(TrustStore::load(&flags.dir)?));
    println!("NAME {}", flags.name);
    println!("ID {}", endpoint.id());
    println!("TICKET {ticket}");
    println!("READY");

    loop {
        let mut link = ServerLink::accept(&endpoint, Arc::clone(&trust)).await?;
        println!("PEER {} trusted={}", link.peer, link.trusted);
        // 每来一台设备就起一条事件泵：Core 的通知按帧推回给对端。
        let closed = Arc::new(tokio::sync::Mutex::new(false));
        if flags.core_port != 0 {
            let send = link.sender();
            let token = flags.core_token.clone();
            let port = flags.core_port;
            let flag = Arc::clone(&closed);
            tokio::spawn(sunday_p2p::events::pump_until_closed(port, token, send, flag));
        }
        let name = flags.name.clone();
        let core_port = flags.core_port;
        let core_token = flags.core_token.clone();
        let result = link
            .serve(move |method, params| {
                let name = name.clone();
                let core_token = core_token.clone();
                async move {
                    match method.as_str() {
                        "ping" => Ok(serde_json::json!({ "pong": true })),
                        "whoami" => Ok(serde_json::json!({ "device": name })),
                        "echo" => Ok(params),
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
                            let body = params.get("body");
                            let (status, answer) =
                                sunday_p2p::call_core("127.0.0.1", core_port, &core_token, &http, &path, body)?;
                            Ok(serde_json::json!({ "status": status, "body": answer }))
                        }
                        other => bail!("unknown method {other}"),
                    }
                }
            })
            .await;
        *closed.lock().await = true;
        match result {
            Ok(()) => println!("PEER-CLOSED {}", link.peer),
            Err(error) => println!("PEER-ERROR {} {error}", link.peer),
        }
        link.close();
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
    let mut client = Client::dial(&endpoint, &flags.ticket, &flags.name).await?;
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
