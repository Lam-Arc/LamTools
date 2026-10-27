// user:“实现这个插件，也正好实验我们的新插件架构”+(Rust 唯一持有网络状态和组件生命周期，页面仅展示)。
mod accelerator;
mod credentials;
mod engines;
mod observe;
mod state;
mod system;
use fs2::FileExt;
use serde_json::{json, Value};
use state::{Controller, Reply};
use std::{fs::OpenOptions, path::PathBuf, time::Duration};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};

#[tokio::main]
async fn main() {
    if let Err(error) = run().await {
        eprintln!("Network Controller: {error}");
        std::process::exit(1);
    }
}
async fn run() -> Result<(), String> {
    let data = std::env::args_os()
        .nth(1)
        .map(PathBuf::from)
        .ok_or("data directory required")?;
    std::fs::create_dir_all(&data).map_err(|e| e.to_string())?;
    let lock = OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(data.join("controller.lock"))
        .map_err(|e| e.to_string())?;
    lock.try_lock_exclusive()
        .map_err(|_| "此插件已经有一个控制器在运行")?;
    let mut controller = Controller::new(data)?;
    controller.recover().await?;
    let mut input = BufReader::new(tokio::io::stdin());
    let mut output = tokio::io::stdout();
    let mut tick = tokio::time::interval(Duration::from_secs(1));
    let mut line = Vec::new();
    loop {
        tokio::select! {
            read = input.read_until(b'\n', &mut line) => {
                if read.map_err(|e| e.to_string())? == 0 { break; }
                if line.len() > 2 * 1024 * 1024 { return Err("request too large".into()); }
                let request: Value = serde_json::from_slice(&line).unwrap_or(json!({}));
                line.clear();
                let method = request["method"].as_str().unwrap_or("");
                let result = controller.call(method, request.get("params").cloned().unwrap_or(json!({}))).await;
                let response = match result { Ok(value) => json!({"id":request["id"],"result":value}), Err(error) => json!({"id":request["id"],"error":error}) };
                let mut bytes = serde_json::to_vec(&response).map_err(|e| e.to_string())?; bytes.push(b'\n');
                output.write_all(&bytes).await.map_err(|e| e.to_string())?;
                output.flush().await.map_err(|e| e.to_string())?;
                if method == "shutdown" { break; }
            }
            _ = tick.tick() => { controller.tick().await; }
        }
    }
    controller.shutdown().await;
    Ok(())
}

pub async fn powershell(script: &str, args: Value) -> Reply {
    let mut command = tokio::process::Command::new("powershell.exe");
    let script = format!(
        "[Console]::InputEncoding=[Text.UTF8Encoding]::new();{}",
        script.replace("$env:SUNDAY_NETWORK_ARGS", "([Console]::In.ReadToEnd())")
    );
    command.args([
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        &script,
    ]);
    command
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .kill_on_drop(true);
    command.env_remove("PSModulePath");
    #[cfg(windows)]
    command.creation_flags(0x08000000);
    let mut child = command.spawn().map_err(|e| e.to_string())?;
    let bytes = args.to_string().into_bytes();
    let mut input = child.stdin.take().ok_or("系统输入不可用")?;
    let output = tokio::time::timeout(Duration::from_secs(20), async move {
        input.write_all(&bytes).await?;
        drop(input);
        child.wait_with_output().await
    })
    .await
    .map_err(|_| "系统查询超过 20 秒，已终止")?
    .map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err("系统命令执行失败；请检查管理员权限、网络适配器或规则是否仍存在".into());
    }
    if output.stdout.len() > 4 * 1024 * 1024 {
        return Err("系统结果过大，请使用筛选".into());
    }
    let text = String::from_utf8_lossy(&output.stdout);
    serde_json::from_str(text.trim().trim_start_matches('\u{feff}'))
        .map_err(|_| "系统未返回有效的 JSON 数据".into())
}
