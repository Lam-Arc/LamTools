//! The PC end of the phone connection.
//!
//! user:“实现 Windows Sunday 与 Android Sunday M 之间的安全远程连接，优先采用 P2P”+
//! (桌面只做两件事：出票据给手机扫，把手机发来的 Core 调用转给本机 Core)。
//!
//! 传输跑在独立的 `sunday-p2p` 进程里，而不是链进桌面应用。原因是依赖：iroh 的
//! `netwatch` 在 Windows 上拉 `wmi`，与桌面端已有的 windows crate 版本冲突，硬合并会
//! 让桌面构建坏掉。user:“P2P 作为独立、可复用的传输组件”+(它本来就是这个定位：
//! 一个独立进程，桌面与手机用同一份实现，宿主只负责起停与转述)。等 iroh 的依赖对齐后
//! 再考虑回到进程内。
//!
//! This is not the old `remote/` gateway: that one needs an account and a self-hosted
//! relay and has no hole punching. Here the transport is iroh, no server of ours involved.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde_json::{json, Value};

pub struct P2pHostState {
    child: Mutex<Option<Child>>,
    ticket: Mutex<String>,
    port: Mutex<u16>,
}

impl Default for P2pHostState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            ticket: Mutex::new(String::new()),
            port: Mutex::new(0),
        }
    }
}

fn data_dir() -> PathBuf {
    let base = std::env::var("APPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::temp_dir());
    base.join("Sunday").join("p2p")
}

/// Where the transport binary is.
///
/// Packaged builds get it next to the app executable; a dev checkout runs it from
/// `core/p2p/target/debug`. `SUNDAY_P2P_BIN` wins over both so a support session can point
/// it anywhere without rebuilding.
fn binary() -> Result<PathBuf, String> {
    if let Ok(explicit) = std::env::var("SUNDAY_P2P_BIN") {
        let path = PathBuf::from(explicit);
        if path.is_file() {
            return Ok(path);
        }
    }
    let name = if cfg!(windows) { "sunday-p2p.exe" } else { "sunday-p2p" };
    let mut candidates = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.join(name));
            candidates.push(dir.join("sunday-p2p").join(name));
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        // dev runs from core/desktop; a packaged build ships the binary next to the app.
        let bases = [
            cwd.join("..").join("p2p"),
            cwd.join("..").join("..").join("p2p"),
            cwd.join("p2p"),
        ];
        for base in bases {
            for profile in ["release", "debug"] {
                candidates.push(base.join("target").join(profile).join(name));
            }
        }
    }
    for candidate in candidates {
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err("找不到 sunday-p2p 传输程序；打包版应放在应用旁边，开发时可先 cargo build".to_owned())
}

/// Starts the transport if it is not already running.
fn ensure_child(api_base: &str, state: &P2pHostState) -> Result<(String, u16), String> {
    let mut guard = state.child.lock().map_err(|_| "传输进程状态不可用".to_string())?;
    if let Some(child) = guard.as_mut() {
        if child.try_wait().ok().flatten().is_none() {
            let ticket = state.ticket.lock().map_err(|_| "票据不可用".to_string())?.clone();
            let port = *state.port.lock().map_err(|_| "端口不可用".to_string())?;
            return Ok((ticket, port));
        }
        *guard = None;
    }

    let parsed = url::Url::parse(api_base.trim()).map_err(|_| "本地后端地址无效".to_string())?;
    if parsed.host_str() != Some("127.0.0.1") && parsed.host_str() != Some("localhost") {
        return Err("只允许回环地址".to_owned());
    }
    let port = parsed.port().ok_or_else(|| "本地后端地址没有端口".to_string())?;
    let core_token = std::env::var("LAMTOOLS_CORE_API_TOKEN").unwrap_or_default();
    let dir = data_dir();
    std::fs::create_dir_all(&dir).ok();
    let name = std::env::var("COMPUTERNAME").unwrap_or_else(|_| "Sunday".to_owned());

    let mut command = Command::new(binary()?);
    command
        .arg("serve")
        .arg("--dir")
        .arg(&dir)
        .arg("--name")
        .arg(name)
        .arg("--core-port")
        .arg(port.to_string())
        .arg("--core-token")
        .arg(core_token)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn().map_err(|error| format!("启动传输进程失败：{error}"))?;

    let stdout = child.stdout.take().ok_or_else(|| "传输进程没有输出".to_string())?;
    let mut reader = BufReader::new(stdout);
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut ticket = String::new();
    let mut line = String::new();
    while std::time::Instant::now() < deadline {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => break,
            Ok(_) => {
                let trimmed = line.trim();
                if let Some(value) = trimmed.strip_prefix("TICKET ") {
                    ticket = value.to_owned();
                }
                if trimmed == "READY" {
                    break;
                }
            }
            Err(_) => break,
        }
    }
    if ticket.is_empty() {
        let _ = child.kill();
        return Err("传输进程没有给出票据".to_owned());
    }
    *state.ticket.lock().map_err(|_| "票据不可用".to_string())? = ticket.clone();
    *state.port.lock().map_err(|_| "端口不可用".to_string())? = port;
    *guard = Some(child);
    Ok((ticket, port))
}

/// The text the phone pastes. Starts the transport on first use.
#[tauri::command]
pub fn p2p_ticket(
    api_base: String,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    let (ticket, port) = ensure_child(&api_base, &state)?;
    Ok(json!({ "ticket": ticket, "port": port }))
}

/// The ticket as an SVG QR code.
///
/// The transport binary owns the encoding; the host only passes the ticket through, so the
/// code the phone scans and the text it pastes are the same string by construction.
#[tauri::command]
pub fn p2p_qr(ticket: String) -> Result<Value, String> {
    // The transport binary owns QR encoding so this host never links the crate: one
    // implementation, two callers, and no second windows dependency graph.
    let mut command = Command::new(binary()?);
    command.arg("qr").arg("--ticket").arg(&ticket);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let output = command
        .output()
        .map_err(|error| format!("生成二维码失败：{error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    Ok(json!({ "svg": String::from_utf8_lossy(&output.stdout) }))
}

/// Kept for symmetry with the phone side; starting the transport is what actually serves.
#[tauri::command]
pub fn p2p_serve_start(
    api_base: String,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    let (ticket, port) = ensure_child(&api_base, &state)?;
    Ok(json!({ "serving": true, "ticket": ticket, "port": port }))
}

/// Stops the transport process and forgets its ticket.
///
/// user:“把这台电脑上的桌面端跑起来”+(传输进程是独立子进程，宿主退出时必须显式收掉：
/// 进程句柄被丢弃不会终止子进程，实测窗口关掉后 sunday-p2p 仍在监听旧票据，
/// 下一次启动又拉起第二个，旧的那个永远指着已经死掉的 Core 端口。)
pub fn stop(state: &P2pHostState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    if let Ok(mut ticket) = state.ticket.lock() {
        ticket.clear();
    }
}

#[tauri::command]
pub fn p2p_serve_stop(state: tauri::State<'_, P2pHostState>) -> Result<Value, String> {
    stop(state.inner());
    Ok(json!({ "serving": false }))
}

#[tauri::command]
pub fn p2p_status(state: tauri::State<'_, P2pHostState>) -> Result<Value, String> {
    let mut serving = false;
    if let Ok(mut guard) = state.child.lock() {
        if let Some(child) = guard.as_mut() {
            serving = child.try_wait().ok().flatten().is_none();
        }
    }
    let ticket = state.ticket.lock().map(|ticket| ticket.clone()).unwrap_or_default();
    Ok(json!({ "serving": serving, "ticket": ticket }))
}

/// user:“允许撤销授权”+(传输进程把名单放在自己的目录里，这里改同一份文件)。
#[tauri::command]
pub fn p2p_devices() -> Result<Value, String> {
    let path = data_dir().join("p2p-trust.json");
    if !path.exists() {
        return Ok(json!({ "devices": [] }));
    }
    let text = std::fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let parsed: Value = serde_json::from_str(&text).map_err(|error| error.to_string())?;
    Ok(json!({ "devices": parsed.get("devices").cloned().unwrap_or_else(|| json!([])) }))
}

#[tauri::command]
pub fn p2p_revoke(id: String) -> Result<Value, String> {
    let path = data_dir().join("p2p-trust.json");
    if !path.exists() {
        return Ok(json!({ "removed": false }));
    }
    let text = std::fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut parsed: Value = serde_json::from_str(&text).map_err(|error| error.to_string())?;
    let Some(list) = parsed.get_mut("devices").and_then(|value| value.as_array_mut()) else {
        return Ok(json!({ "removed": false }));
    };
    let before = list.len();
    list.retain(|device| device.get("id").and_then(|value| value.as_str()) != Some(id.as_str()));
    let removed = list.len() != before;
    if removed {
        std::fs::write(&path, serde_json::to_string_pretty(&parsed).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())?;
    }
    Ok(json!({ "removed": removed }))
}
