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
}

fn parse(args: Vec<String>) -> Result<Flags> {
    let mut flags = Flags {
        dir: PathBuf::from("."),
        name: hostname(),
        ticket: String::new(),
        method: "ping".to_owned(),
        params: "{}".to_owned(),
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
        let name = flags.name.clone();
        let result = link
            .serve(move |method, params| {
                let name = name.clone();
                async move {
                    match method.as_str() {
                        "ping" => Ok(serde_json::json!({ "pong": true })),
                        "whoami" => Ok(serde_json::json!({ "device": name })),
                        "echo" => Ok(params),
                        other => bail!("unknown method {other}"),
                    }
                }
            })
            .await;
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
    client.close();
    endpoint.close().await;
    Ok(())
}
