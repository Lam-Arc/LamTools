//! 安卓设备控制的本机通道。
//!
//! user:“加，安卓控制，上模拟器里把它跑通”+(Core 的工具要能让手机读屏、点按、输入，
//! 但工具跑在 guest 里，碰不到 Tauri 命令，也碰不到 Kotlin)。这里做三件事：
//!
//! 1. 在 127.0.0.1 上开一个只认本机的小 HTTP 端点；
//! 2. 把端口和一次性令牌写进 guest 能读到的 userdata 目录；
//! 3. 收到请求就通过 JNI 交给 `DeviceControlBridge`，由无障碍服务执行。
//!
//! 不做端口转发、不监听外部地址：只有这台手机上、读过那个文件的进程能调用。

use std::io::{Read, Write};
#[cfg(target_os = "android")]
use std::net::TcpListener;
use std::net::TcpStream;
use std::path::PathBuf;
#[cfg(target_os = "android")]
use std::sync::OnceLock;

#[cfg(target_os = "android")]
use jni::objects::{GlobalRef, JObject, JString, JValue};

#[cfg(target_os = "android")]
static VM: OnceLock<jni::JavaVM> = OnceLock::new();

#[cfg(target_os = "android")]
static BRIDGE: OnceLock<BridgeClass> = OnceLock::new();

#[cfg(target_os = "android")]
struct BridgeClass(GlobalRef);

#[cfg(target_os = "android")]
unsafe impl Send for BridgeClass {}

#[cfg(target_os = "android")]
unsafe impl Sync for BridgeClass {}

/// 服务起好之后写给 guest 的连接信息；工具每次调用前读它。
pub fn start(userdata: PathBuf) {
    #[cfg(target_os = "android")]
    {
        std::fs::create_dir_all(&userdata).ok();
        let listener = match TcpListener::bind(("127.0.0.1", 0)) {
            Ok(listener) => listener,
            Err(error) => {
                eprintln!("[sunday] device control cannot bind: {error}");
                return;
            }
        };
        let port = match listener.local_addr() {
            Ok(address) => address.port(),
            Err(error) => {
                eprintln!("[sunday] device control cannot read its port: {error}");
                return;
            }
        };
        let token = random_token();
        // user:“无障碍服务没开要如实说”+(工具先读这个文件确认通道在，再读到服务没开时
        // 让人去系统设置里打开，而不是返回空界面让模型以为点成功了)。
        let path = userdata.join("device-control.json");
        let payload = format!(
            "{{\"port\":{port},\"token\":\"{token}\",\"protocol\":1}}"
        );
        if let Err(error) = std::fs::write(&path, payload) {
            eprintln!("[sunday] device control cannot write {}: {error}", path.display());
            return;
        }
        println!("[sunday] device control on 127.0.0.1:{port}");

        std::thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                let token = token.clone();
                std::thread::spawn(move || handle(stream, &token));
            }
        });
    }
    #[cfg(not(target_os = "android"))]
    {
        let _ = userdata;
    }
}

#[cfg(target_os = "android")]
fn random_token() -> String {
    use std::io::Read as _;
    let mut bytes = [0u8; 24];
    if let Ok(mut file) = std::fs::File::open("/dev/urandom") {
        let _ = file.read_exact(&mut bytes);
    } else {
        // 退路：时间与进程号；只在本机回环上用一个进程生命周期，够用。
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|elapsed| elapsed.as_nanos())
            .unwrap_or(0);
        bytes[..8].copy_from_slice(&nanos.to_le_bytes()[..8]);
        let pid = std::process::id().to_le_bytes();
        bytes[8..12].copy_from_slice(&pid);
    }
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn handle(mut stream: TcpStream, token: &str) {
    let mut buffer = Vec::new();
    let mut chunk = [0u8; 4096];
    let header_end = loop {
        match stream.read(&mut chunk) {
            Ok(0) => return,
            Ok(count) => buffer.extend_from_slice(&chunk[..count]),
            Err(_) => return,
        }
        if let Some(at) = buffer.windows(4).position(|window| window == b"\r\n\r\n") {
            break at;
        }
        if buffer.len() > 64 * 1024 {
            let _ = respond(&mut stream, 400, "{\"ok\":false,\"error\":\"header too large\"}");
            return;
        }
    };
    let head = String::from_utf8_lossy(&buffer[..header_end]).to_string();
    let mut lines = head.split("\r\n");
    let request_line = lines.next().unwrap_or("");
    if !request_line.starts_with("POST /device-control ") {
        let _ = respond(&mut stream, 404, "{\"ok\":false,\"error\":\"not found\"}");
        return;
    }
    let mut authorized = false;
    let mut length = 0usize;
    for line in lines {
        if let Some((name, value)) = line.split_once(':') {
            let name = name.trim().to_ascii_lowercase();
            let value = value.trim();
            if name == "x-sunday-token" && value == token {
                authorized = true;
            }
            if name == "content-length" {
                length = value.parse().unwrap_or(0);
            }
        }
    }
    if !authorized {
        let _ = respond(&mut stream, 403, "{\"ok\":false,\"error\":\"token\"}");
        return;
    }
    if length > 1024 * 1024 {
        let _ = respond(&mut stream, 400, "{\"ok\":false,\"error\":\"body too large\"}");
        return;
    }
    let mut body = buffer[header_end + 4..].to_vec();
    while body.len() < length {
        match stream.read(&mut chunk) {
            Ok(0) => break,
            Ok(count) => body.extend_from_slice(&chunk[..count]),
            Err(_) => break,
        }
    }
    body.truncate(length);

    let request = String::from_utf8_lossy(&body).to_string();
    let answer = match call_bridge(&request) {
        Ok(text) if !text.is_empty() => text,
        Ok(_) => "{\"ok\":false,\"error\":\"empty answer\"}".to_owned(),
        Err(error) => serde_json::json!({ "ok": false, "error": error }).to_string(),
    };
    let _ = respond(&mut stream, 200, &answer);
}

fn respond(stream: &mut TcpStream, status: u16, body: &str) -> std::io::Result<()> {
    let reason = match status {
        200 => "OK",
        400 => "Bad Request",
        403 => "Forbidden",
        _ => "Not Found",
    };
    let response = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    stream.write_all(response.as_bytes())
}

/// 让 Rust 在第一次拿到 JNIEnv 时记住 JavaVM 与桥类。
///
/// 必须从有应用类加载器的线程调用，否则 `find_class` 只能找到 boot loader，
/// 第一次调用就是 ClassNotFoundException。
#[cfg(target_os = "android")]
pub fn remember(env: &mut jni::JNIEnv) {
    if VM.get().is_none() {
        if let Ok(vm) = env.get_java_vm() {
            let _ = VM.set(vm);
        }
    }
    if BRIDGE.get().is_none() {
        if let Ok(class) = env.find_class("com/lamtools/sunday/core/DeviceControlBridge") {
            if let Ok(global) = env.new_global_ref(class) {
                let _ = BRIDGE.set(BridgeClass(global));
            }
        }
    }
}

#[cfg(target_os = "android")]
fn call_bridge(request: &str) -> Result<String, String> {
    let vm = VM
        .get()
        .ok_or_else(|| "the Android runtime is not ready".to_owned())?;
    let class = BRIDGE
        .get()
        .ok_or_else(|| "the device control bridge is not ready".to_owned())?;
    let mut env = vm
        .attach_current_thread()
        .map_err(|error| error.to_string())?;
    let argument = env
        .new_string(request)
        .map_err(|error| error.to_string())?;
    let result = env
        .call_static_method(
            &class.0,
            "action",
            "(Ljava/lang/String;)Ljava/lang/String;",
            &[JValue::Object(&argument)],
        )
        .map_err(|error| error.to_string())?;
    let object: JObject = result.l().map_err(|error| error.to_string())?;
    let text: String = env
        .get_string(&JString::from(object))
        .map_err(|error| error.to_string())?
        .into();
    Ok(text)
}

#[cfg(not(target_os = "android"))]
fn call_bridge(_request: &str) -> Result<String, String> {
    Err("设备控制只在安卓上可用".to_owned())
}
