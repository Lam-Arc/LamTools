use super::{
    gateway::{GatewayStartOptions, RemoteGatewayManager},
    identity::random_token,
    secure_store::DesktopAccountSession,
};
use serde::Serialize;
use std::{
    fs,
    io::{Read, Write},
    net::{Shutdown, TcpListener, TcpStream},
    path::PathBuf,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::Duration,
};

#[derive(Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct ControlDiscovery {
    port: u16,
    token: String,
    pid: u32,
}

pub fn control_discovery_path() -> PathBuf {
    std::env::temp_dir().join("lamtools-remote-control.json")
}

/// Handle for the loopback CLI control listener.  Keeping the listener
/// lifetime explicit prevents a discovery file from surviving a normal app
/// shutdown and being mistaken for a live desktop by the next CLI call.
pub struct ControlServer {
    stop: Arc<AtomicBool>,
    join: Mutex<Option<JoinHandle<()>>>,
    token: String,
}

impl ControlServer {
    pub fn stop(&self) {
        if self.stop.swap(true, Ordering::SeqCst) {
            return;
        }
        // Wake the non-blocking accept loop immediately.
        if let Ok(discovery) = read_discovery() {
            let _ = TcpStream::connect(("127.0.0.1", discovery.port));
        }
        if let Ok(mut join) = self.join.lock() {
            if let Some(handle) = join.take() {
                let _ = handle.join();
            }
        }
        remove_discovery_if_owned(&self.token);
    }
}

impl Drop for ControlServer {
    fn drop(&mut self) {
        self.stop();
    }
}

pub fn start_local_control_server(
    manager: RemoteGatewayManager,
    core_api_base: String,
) -> Result<ControlServer, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|error| error.to_string())?;
    listener
        .set_nonblocking(true)
        .map_err(|error| error.to_string())?;
    let port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    let token = random_token(32)?;
    let discovery = ControlDiscovery {
        port,
        token: token.clone(),
        pid: std::process::id(),
    };
    fs::write(
        control_discovery_path(),
        serde_json::to_vec(&discovery).map_err(|e| e.to_string())?,
    )
    .map_err(|error| format!("无法写入手机控制 CLI 状态：{error}"))?;
    let stop = Arc::new(AtomicBool::new(false));
    let thread_stop = stop.clone();
    let thread_token = token.clone();
    let join = match thread::Builder::new()
        .name("lamtools-remote-control-cli".to_string())
        .spawn(move || {
            while !thread_stop.load(Ordering::SeqCst) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        if thread_stop.load(Ordering::SeqCst) {
                            let _ = stream.shutdown(Shutdown::Both);
                            break;
                        }
                        let _ = handle(&mut stream, &manager, &core_api_base, &thread_token);
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(20));
                    }
                    Err(_) => {
                        thread::sleep(Duration::from_millis(50));
                    }
                }
            }
        }) {
        Ok(join) => join,
        Err(error) => {
            remove_discovery_if_owned(&token);
            return Err(error.to_string());
        }
    };
    Ok(ControlServer {
        stop,
        join: Mutex::new(Some(join)),
        token,
    })
}

fn read_discovery() -> Result<ControlDiscovery, String> {
    let bytes = fs::read(control_discovery_path()).map_err(|error| error.to_string())?;
    serde_json::from_slice(&bytes).map_err(|error| error.to_string())
}

fn remove_discovery_if_owned(token: &str) {
    let Ok(discovery) = read_discovery() else {
        return;
    };
    if !constant_time_eq(discovery.token.as_bytes(), token.as_bytes()) {
        return;
    }
    let _ = fs::remove_file(control_discovery_path());
}

fn handle(
    stream: &mut TcpStream,
    manager: &RemoteGatewayManager,
    core_api_base: &str,
    token: &str,
) -> Result<(), String> {
    let mut buffer = vec![0_u8; 64 * 1024];
    let read = stream.read(&mut buffer).map_err(|e| e.to_string())?;
    let request = String::from_utf8_lossy(&buffer[..read]);
    let mut lines = request.split("\r\n");
    let request_line = lines.next().unwrap_or_default();
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or_default();
    let path = parts.next().unwrap_or_default();
    let authorized = lines
        .filter_map(|line| line.split_once(':'))
        .any(|(name, value)| {
            name.eq_ignore_ascii_case("x-lamtools-control")
                && constant_time_eq(value.trim().as_bytes(), token.as_bytes())
        });
    if !authorized {
        return respond(stream, 401, &serde_json::json!({"error":"unauthorized"}));
    }
    let body = request
        .split_once("\r\n\r\n")
        .map(|(_, body)| body)
        .unwrap_or_default();
    let result = match (method, path) {
        ("GET", "/status") => manager
            .status()
            .map(|value| serde_json::to_value(value).unwrap()),
        ("POST", "/start") => manager
            .start(core_api_base, GatewayStartOptions::default())
            .map(|value| serde_json::to_value(value).unwrap()),
        ("POST", "/stop") => manager
            .stop()
            .map(|value| serde_json::to_value(value).unwrap()),
        ("POST", "/pairing") => manager
            .pairing_create()
            .map(|value| serde_json::to_value(value).unwrap()),
        ("GET", "/devices") => manager
            .status()
            .map(|value| serde_json::to_value(value.trusted_devices).unwrap()),
        ("POST", "/identity") => serde_json::from_str::<serde_json::Value>(body)
            .map_err(|error| format!("桌面账号身份参数无效：{error}"))
            .and_then(|value| {
                let server_id = value
                    .get("serverId")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default();
                let username = value
                    .get("username")
                    .and_then(|value| value.as_str())
                    .unwrap_or_default();
                manager
                    .node_identity_for_account(server_id, username)
                    .map(|value| serde_json::to_value(value).unwrap())
            }),
        ("POST", "/account") => serde_json::from_str::<DesktopAccountSession>(body)
            .map_err(|error| format!("桌面账号会话无效：{error}"))
            .and_then(|session| {
                manager
                    .save_account_session(session)
                    .map(|value| serde_json::to_value(value).unwrap())
            }),
        ("DELETE", value) if value.starts_with("/devices/") => manager
            .revoke_device(&value[9..])
            .map(|value| serde_json::json!({"revoked":value})),
        _ => return respond(stream, 404, &serde_json::json!({"error":"not found"})),
    };
    match result {
        Ok(value) => respond(stream, 200, &value),
        Err(error) => respond(stream, 400, &serde_json::json!({"error":error})),
    }
}

fn respond(stream: &mut TcpStream, status: u16, value: &serde_json::Value) -> Result<(), String> {
    let body = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    let reason = if status == 200 {
        "OK"
    } else if status == 401 {
        "Unauthorized"
    } else if status == 404 {
        "Not Found"
    } else {
        "Bad Request"
    };
    write!(stream, "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", body.len()).map_err(|e| e.to_string())?;
    stream.write_all(&body).map_err(|e| e.to_string())
}

fn constant_time_eq(left: &[u8], right: &[u8]) -> bool {
    if left.len() != right.len() {
        return false;
    }
    let mut difference = 0_u8;
    for (a, b) in left.iter().zip(right) {
        difference |= a ^ b;
    }
    difference == 0
}
