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
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};

#[derive(Clone, Default)]
pub struct P2pHostState {
    child: Arc<Mutex<Option<Child>>>,
    ticket: Arc<Mutex<String>>,
    port: Arc<Mutex<u16>>,
    /// 当前连着的手机；空表示没有设备在线。
    ///
    /// user:“我根本不知道卡在哪里了”+(电脑这边也要看得见手机到底连上没有，
    /// 否则二维码摆在屏幕上，连接成没成全靠猜)。
    peer: Arc<Mutex<Option<String>>>,
    /// 最近一次启动传输进程用的后端地址：进程死掉之后照它重启。
    api_base: Arc<Mutex<String>>,
    /// 守护线程已经起来（一个进程只要一条）。
    supervisord: Arc<AtomicBool>,
    /// 宿主正在退出：守护线程不要再拉起新进程。
    stopping: Arc<AtomicBool>,
    /// 同一张票据的二维码只生成一次（每次生成都要起一次子进程）。
    qr_cache: Arc<Mutex<(String, String)>>,
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
    // 宿主可以重新开始服务了；守护线程据此恢复工作。
    state.stopping.store(false, Ordering::SeqCst);
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
    if let Ok(mut slot) = state.ticket.lock() {
        *slot = ticket.clone();
    }
    if let Ok(mut slot) = state.port.lock() {
        *slot = port;
    }
    if let Ok(mut slot) = state.api_base.lock() {
        *slot = api_base.trim().to_owned();
    }

    // 继续读传输进程的输出：网络变化会打一行新的 TICKET，配对失败时会有 PEER 和错误。
    // user:“连不上……一点反应都没有”+(排障需要证据；之前 READY 之后就不再读管道，
    // 对端是否连到、中继是否可用全都丢了)。
    let log_path = data_dir().join("p2p.log");
    let ticket_slot = Arc::clone(&state.ticket);
    let peer_slot = Arc::clone(&state.peer);
    let stderr = child.stderr.take();
    spawn_log_reader(log_path.clone(), reader, Some(ticket_slot), Some(peer_slot));
    if let Some(stderr) = stderr {
        spawn_log_reader(log_path, BufReader::new(stderr), None, None);
    }

    *guard = Some(child);
    // 进程起来之后交给守护线程：它死了（崩溃、被系统收掉）就照原来的地址重启，
    // 否则手机要等到用户手动打开「设备连接」才能重新连上。
    supervise(state);
    Ok((ticket, port))
}

/// 一条常驻线程盯着传输进程。
///
/// user:“传输进程死了只能手动重新生成二维码”+(以前只有打开设备页才会检查子进程，
/// 手机那边于是长时间连不上任何东西，界面上也看不出原因)。
fn supervise(state: &P2pHostState) {
    if state.supervisord.swap(true, Ordering::SeqCst) {
        return;
    }
    let host = state.clone();
    std::thread::spawn(move || loop {
        std::thread::sleep(std::time::Duration::from_secs(3));
        // 宿主退出期间不要重启：进程会在退出时被杀掉。
        if host.stopping.load(Ordering::SeqCst) {
            continue;
        }
        let api = host
            .api_base
            .lock()
            .map(|value| value.clone())
            .unwrap_or_default();
        if api.is_empty() {
            continue;
        }
        let exited = {
            let mut guard = match host.child.lock() {
                Ok(guard) => guard,
                Err(_) => continue,
            };
            match guard.as_mut() {
                None => true,
                Some(child) => child.try_wait().ok().flatten().is_some(),
            }
        };
        if !exited {
            continue;
        }
        if let Ok(mut guard) = host.child.lock() {
            *guard = None;
        }
        if let Err(error) = ensure_child(&api, &host) {
            eprintln!("[sunday] p2p supervisor: {error}");
        }
    });
}

/// 把子进程的后续输出写进 `%APPDATA%/Sunday/p2p/p2p.log`，顺便更新票据。
fn spawn_log_reader(
    path: PathBuf,
    mut reader: BufReader<impl std::io::Read + Send + 'static>,
    ticket: Option<Arc<Mutex<String>>>,
    peer: Option<Arc<Mutex<Option<String>>>>,
) {
    std::thread::spawn(move || {
        use std::io::Write;
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .ok();
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    let trimmed = line.trim();
                    if trimmed.is_empty() {
                        continue;
                    }
                    if let Some(value) = trimmed.strip_prefix("TICKET ") {
                        if let Some(slot) = &ticket {
                            if let Ok(mut current) = slot.lock() {
                                *current = value.to_owned();
                            }
                        }
                    }
                    // 传输进程每接上一台设备打印 PEER，断开时打印 PEER-CLOSED / PEER-ERROR。
                    if let Some(rest) = trimmed.strip_prefix("PEER ") {
                        let id = rest.split_whitespace().next().unwrap_or("").to_owned();
                        if let Some(slot) = &peer {
                            if let Ok(mut current) = slot.lock() {
                                *current = Some(id);
                            }
                        }
                    } else if trimmed.starts_with("PEER-CLOSED") || trimmed.starts_with("PEER-ERROR") {
                        if let Some(slot) = &peer {
                            if let Ok(mut current) = slot.lock() {
                                *current = None;
                            }
                        }
                    }
                    if let Some(file) = file.as_mut() {
                        let _ = writeln!(file, "{trimmed}");
                        let _ = file.flush();
                    }
                }
            }
        }
    });
}

/// The text the phone pastes. Starts the transport on first use.
///
/// 异步命令：启动要等中继和 READY（最长 30 秒），不能把 IPC 线程堵在那里让整个窗口没反应。
#[tauri::command]
pub async fn p2p_ticket(
    api_base: String,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    let host = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || ensure_child(&api_base, &host))
        .await
        .map_err(|error| error.to_string())?
        .map(|(ticket, port)| json!({ "ticket": ticket, "port": port }))
}

/// The ticket as an SVG QR code.
///
/// The transport binary owns the encoding; the host only passes the ticket through, so the
/// code the phone scans and the text it pastes are the same string by construction.
#[tauri::command]
pub async fn p2p_qr(
    ticket: String,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    // 同一张票据只渲染一次：每次渲染都要起一个进程，设备页每 3 秒刷新一次不该反复起进程。
    if let Ok(cache) = state.qr_cache.lock() {
        if cache.0 == ticket && !cache.1.is_empty() {
            return Ok(json!({ "svg": cache.1 }));
        }
    }
    let requested = ticket.clone();
    let svg = tauri::async_runtime::spawn_blocking(move || build_qr(&requested))
        .await
        .map_err(|error| error.to_string())??;
    if let Ok(mut cache) = state.qr_cache.lock() {
        cache.0 = ticket;
        cache.1 = svg.clone();
    }
    Ok(json!({ "svg": svg }))
}

/// The transport binary owns QR encoding so this host never links the crate: one
/// implementation, two callers, and no second windows dependency graph.
fn build_qr(ticket: &str) -> Result<String, String> {
    let mut command = Command::new(binary()?);
    command.arg("qr").arg("--ticket").arg(ticket);
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
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Kept for symmetry with the phone side; starting the transport is what actually serves.
#[tauri::command]
pub async fn p2p_serve_start(
    api_base: String,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    let host = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || ensure_child(&api_base, &host))
        .await
        .map_err(|error| error.to_string())?
        .map(|(ticket, port)| json!({ "serving": true, "ticket": ticket, "port": port }))
}

/// Stops the transport process and forgets its ticket.
///
/// user:“把这台电脑上的桌面端跑起来”+(传输进程是独立子进程，宿主退出时必须显式收掉：
/// 进程句柄被丢弃不会终止子进程，实测窗口关掉后 sunday-p2p 仍在监听旧票据，
/// 下一次启动又拉起第二个，旧的那个永远指着已经死掉的 Core 端口。)
pub fn stop(state: &P2pHostState) {
    state.stopping.store(true, Ordering::SeqCst);
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    if let Ok(mut ticket) = state.ticket.lock() {
        ticket.clear();
    }
    if let Ok(mut peer) = state.peer.lock() {
        *peer = None;
    }
    if let Ok(mut api) = state.api_base.lock() {
        api.clear();
    }
    if let Ok(mut cache) = state.qr_cache.lock() {
        cache.0.clear();
        cache.1.clear();
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
    let peer = state.peer.lock().ok().and_then(|slot| slot.clone());
    Ok(json!({
        "serving": serving,
        "ticket": ticket,
        "connected": peer.is_some(),
        "peer": peer,
    }))
}

/// user:“允许撤销授权”+(传输进程把名单放在自己的目录里，这里改同一份文件)。
///
/// 传输进程每次握手前都会重读这份名单，所以撤销立即生效，不需要重启进程。
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
