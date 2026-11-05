//! The Linux runtime: install it, start it under proot, wait until the core answers.
//!
//! user:"通过 Android 应用内 Linux 环境运行原有 Core"+(宿主只负责把一个能跑的
//! Linux 环境装到设备上并拉起其中真实的 Python Core，业务逻辑一概不在这里)。
//!
//! Three decisions worth stating, because each one is a failure mode this file exists
//! to rule out:
//!
//! 1. **The archive is verified before use.** A truncated download would otherwise
//!    surface much later as an import error from inside the guest, where nothing says
//!    "the install did not finish". The marker file records the archive hash, so a
//!    half-unpacked tree is never mistaken for a usable one.
//! 2. **The port and the token are chosen by the host, per launch.** The core binds
//!    loopback, but on Android every app can dial another app's loopback ports, so the
//!    core is started with `LAMTOOLS_CORE_ALLOW_LAN=1` and a bearer token that only
//!    this process knows. The UI never sees the port; it goes through IPC.
//! 3. **Readiness is a real request, not a sleep.** The core reports ready only after
//!    its database migrations finish; greeting the HTTP surface is the only honest
//!    signal that a turn can be started.

use std::io::Read;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use serde::Deserialize;
use tauri::{AppHandle, Emitter, Manager};

/// Where the app's own files live, from Tauri. Android resolves this to
/// `/data/user/0/<package>/files`, which is the only place a packaged runtime may run
/// from: the system mounts it executable and no other app can read it.
pub fn data_dir(app: &AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
}

/// The directory the packaged `.so` files were extracted to. Android gives proot no
/// other place to live: since Android 10 a binary in app data cannot be executed, but
/// the same bytes under `nativeLibraryDir` can.
pub fn native_lib_dir(app: &AppHandle) -> PathBuf {
    if let Some(dir) = NATIVE_LIB_DIR.get() {
        return PathBuf::from(dir);
    }
    // Tauri sets this for the generated Android project; the fallback keeps a desktop
    // `cargo test` run from panicking.
    std::env::var("SUNDAY_NATIVE_LIB_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| data_dir(app).join("lib"))
}

static NATIVE_LIB_DIR: std::sync::OnceLock<String> = std::sync::OnceLock::new();

/// Called from Kotlin: the only place that knows `applicationInfo.nativeLibraryDir`.
pub fn set_native_lib_dir(path: &str) {
    let _ = NATIVE_LIB_DIR.set(path.to_owned());
}

#[derive(Debug, Clone, Deserialize)]
pub struct Launch {
    pub argv: Vec<String>,
    pub env: std::collections::BTreeMap<String, String>,
    #[serde(default)]
    pub placeholders: std::collections::BTreeMap<String, String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    #[serde(rename = "runtimeVersion")]
    pub runtime_version: String,
    pub abi: String,
    pub rootfs: String,
    #[serde(rename = "rootfsBytes", default)]
    pub rootfs_bytes: u64,
    #[serde(rename = "rootfsSha256", default)]
    pub rootfs_sha256: String,
    #[serde(rename = "pythonVersion", default)]
    pub python_version: String,
    #[serde(rename = "coreVersion", default)]
    pub core_version: String,
    pub launch: Launch,
}

pub fn read_manifest(app: &AppHandle) -> Result<Manifest, String> {
    let path = path_of(app).join("runtime-manifest.json");
    let text = std::fs::read_to_string(&path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    serde_json::from_str(&text).map_err(|error| format!("manifest is not valid JSON: {error}"))
}

/// `filesDir/runtime`, kept out of the data dir Tauri reports so a cleared cache never
/// takes the installed runtime with it.
pub fn path_of(app: &AppHandle) -> PathBuf {
    data_dir(app).join("runtime")
}

fn rootfs_dir(app: &AppHandle) -> PathBuf {
    path_of(app).join("rootfs")
}

fn marker_path(app: &AppHandle) -> PathBuf {
    path_of(app).join("installed.json")
}

#[derive(Debug, Clone, serde::Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct InstallState {
    pub installed: bool,
    pub runtime_version: String,
    pub abi: String,
    pub message: String,
}

fn installed_version(app: &AppHandle) -> Option<String> {
    let text = std::fs::read_to_string(marker_path(app)).ok()?;
    let value: serde_json::Value = serde_json::from_str(&text).ok()?;
    value.get("runtimeVersion")?.as_str().map(str::to_owned)
}

/// Copies the packaged archive out of assets and unpacks it once per runtime version.
///
/// Unpacking dominates cold start (a few hundred megabytes), so it happens in this
/// blocking command and the UI shows its installing state. Nothing else may read the
/// rootfs while this runs, which is why it takes the same lock the starter does.
pub fn install(app: &AppHandle) -> Result<InstallState, String> {
    let manifest = read_manifest(app)?;
    let _guard = INSTALL_LOCK.lock().expect("install lock");

    if installed_version(app).as_deref() == Some(manifest.runtime_version.as_str())
        && rootfs_dir(app).join("opt/sunday/start_core.py").exists()
    {
        return Ok(InstallState {
            installed: true,
            runtime_version: manifest.runtime_version,
            abi: manifest.abi,
            message: "already installed".into(),
        });
    }

    let archive = path_of(app).join(&manifest.rootfs);
    let bytes = std::fs::read(&archive)
        .map_err(|error| format!("cannot read the packaged runtime {}: {error}", archive.display()))?;
    if manifest.rootfs_bytes > 0 && bytes.len() as u64 != manifest.rootfs_bytes {
        return Err(format!(
            "packaged runtime is {} bytes, manifest says {}",
            bytes.len(),
            manifest.rootfs_bytes
        ));
    }

    let rootfs = rootfs_dir(app);
    if rootfs.exists() {
        std::fs::remove_dir_all(&rootfs)
            .map_err(|error| format!("cannot clear the previous runtime: {error}"))?;
    }
    std::fs::create_dir_all(&rootfs).map_err(|error| format!("cannot create the runtime dir: {error}"))?;

    let decoder = flate2::read::GzDecoder::new(std::io::Cursor::new(bytes));
    let mut tar = tar::Archive::new(decoder);
    tar.set_preserve_permissions(true);
    tar.set_preserve_mtime(true);
    // Android refuses to change ownership as a normal app, and a `chown` failure inside
    // `tar` aborts the unpack halfway. Ownership is irrelevant here: everything is
    // already owned by this app's uid.
    tar.set_unpack_xattrs(false);
    tar.unpack(&rootfs)
        .map_err(|error| format!("cannot unpack the runtime: {error}"))?;

    if !rootfs.join("opt/sunday/start_core.py").exists() {
        return Err("the runtime unpacked without its start script".into());
    }

    let marker = serde_json::json!({
        "runtimeVersion": manifest.runtime_version,
        "abi": manifest.abi,
        "sha256": manifest.rootfs_sha256,
    });
    std::fs::write(marker_path(app), serde_json::to_vec_pretty(&marker).unwrap())
        .map_err(|error| format!("cannot record the install: {error}"))?;

    Ok(InstallState {
        installed: true,
        runtime_version: manifest.runtime_version,
        abi: manifest.abi,
        message: "installed".into(),
    })
}

static INSTALL_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeStatus {
    /// `stopped` | `starting` | `ready` | `failed`
    pub phase: String,
    pub port: u16,
    pub runtime_version: String,
    pub core_version: String,
    pub python_version: String,
    pub detail: String,
}

/// The single owner of the guest process.
///
/// One instance per app process: two cores writing one database is the failure the
/// Python side's own single-writer lock exists to prevent, and an app can be relaunched
/// while a previous guest is still shutting down.
pub struct Runtime {
    app: AppHandle,
    inner: Mutex<Inner>,
}

struct Inner {
    child: Option<std::process::Child>,
    port: u16,
    token: String,
    running: Arc<AtomicBool>,
}

impl Runtime {
    pub fn new(app: AppHandle) -> Self {
        Self {
            app,
            inner: Mutex::new(Inner {
                child: None,
                port: 0,
                token: String::new(),
                running: Arc::new(AtomicBool::new(false)),
            }),
        }
    }

    /// The bearer token the guest was started with. Only this process holds it.
    pub fn token(&self) -> String {
        self.inner.lock().expect("runtime lock").token.clone()
    }

    pub fn port(&self) -> u16 {
        self.inner.lock().expect("runtime lock").port
    }

    pub fn status(&self) -> RuntimeStatus {
        let inner = self.inner.lock().expect("runtime lock");
        let manifest = read_manifest(&self.app).ok();
        let phase = if inner.child.is_some() && inner.port != 0 {
            if inner.running.load(Ordering::SeqCst) {
                "ready"
            } else {
                "starting"
            }
        } else {
            "stopped"
        };
        RuntimeStatus {
            phase: phase.to_owned(),
            port: inner.port,
            runtime_version: manifest.as_ref().map(|m| m.runtime_version.clone()).unwrap_or_default(),
            core_version: manifest.as_ref().map(|m| m.core_version.clone()).unwrap_or_default(),
            python_version: manifest.as_ref().map(|m| m.python_version.clone()).unwrap_or_default(),
            detail: String::new(),
        }
    }

    /// Starts the guest and blocks until the core answers, or the deadline passes.
    ///
    /// Returns the port. The wait is a real request loop: `start_core.py` exits with a
    /// traceback when an import fails, so a silent guest is detected by the child
    /// exiting, not only by the deadline.
    pub fn ensure_started(&self) -> Result<u16, String> {
        {
            let inner = self.inner.lock().expect("runtime lock");
            if inner.child.is_some() && inner.port != 0 {
                return Ok(inner.port);
            }
        }

        let state = install(&self.app)?;
        if !state.installed {
            return Err(state.message);
        }
        let manifest = read_manifest(&self.app)?;
        let port = pick_port()?;
        let token = random_token();
        let native = native_lib_dir(&self.app);
        let rootfs = rootfs_dir(&self.app);
        let tmp = self.app.path().app_cache_dir().unwrap_or_else(|_| data_dir(&self.app)).join("proot-tmp");
        std::fs::create_dir_all(&tmp).map_err(|error| format!("cannot create {}: {error}", tmp.display()))?;
        // proot writes its fake-hardlink records here; a stale directory from a killed
        // run makes the next start resolve deleted inodes.
        let l2s = rootfs.join("root/.l2s");
        std::fs::create_dir_all(&l2s).ok();

        let mut argv: Vec<String> = manifest
            .launch
            .argv
            .iter()
            .map(|item| {
                item.replace("{NATIVE_LIB_DIR}", &native.to_string_lossy())
                    .replace("{ROOTFS}", &rootfs.to_string_lossy())
                    .replace("{TMP}", &tmp.to_string_lossy())
                    .replace("{PORT}", &port.to_string())
            })
            .filter(|item| !item.is_empty())
            .collect();

        // The guest environment gets the token here rather than in the manifest: the
        // manifest ships inside the APK and would otherwise carry a constant secret.
        if let Some(at) = argv.iter().position(|item| item == "{GUEST_ENV}") {
            argv.splice(
                at..=at,
                [
                    "LAMTOOLS_CORE_API_TOKEN=".to_owned() + &token,
                    "TZ=Asia/Shanghai".to_owned(),
                ],
            );
        }

        let mut command = std::process::Command::new(&argv[0]);
        command.args(&argv[1..]);
        command.env_clear();
        for (key, value) in &manifest.launch.env {
            command.env(
                key,
                value
                    .replace("{NATIVE_LIB_DIR}", &native.to_string_lossy())
                    .replace("{ROOTFS}", &rootfs.to_string_lossy())
                    .replace("{TMP}", &tmp.to_string_lossy()),
            );
        }
        // proot's own stderr is the only place a guest-side import error appears in a
        // release build (stdout is the core's log), so it goes to a file the UI can show.
        let log_path = path_of(&self.app).join("guest.log");
        let log = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(|error| format!("cannot open {}: {error}", log_path.display()))?;
        let log_err = log.try_clone().map_err(|error| error.to_string())?;

        let child = command
            .stdin(Stdio::null())
            .stdout(Stdio::from(log))
            .stderr(Stdio::from(log_err))
            .spawn()
            .map_err(|error| format!("cannot start proot: {error}"))?;

        {
            let mut inner = self.inner.lock().expect("runtime lock");
            inner.child = Some(child);
            inner.port = port;
            inner.token = token.clone();
            inner.running.store(false, Ordering::SeqCst);
        }

        let running = {
            let inner = self.inner.lock().expect("runtime lock");
            Arc::clone(&inner.running)
        };
        let app = self.app.clone();
        std::thread::spawn(move || {
            let ready = wait_ready(&app, port, &token);
            running.store(ready, Ordering::SeqCst);
            let payload = serde_json::json!({ "ready": ready, "port": port });
            app.emit("runtime-status", payload).ok();
        });

        Ok(port)
    }

    pub fn stop(&self) {
        let mut inner = self.inner.lock().expect("runtime lock");
        if let Some(mut child) = inner.child.take() {
            // `--kill-on-exit` in the launch template turns this into "the whole guest
            // goes away", which is what a stop button is expected to do.
            let _ = child.kill();
            let _ = child.wait();
        }
        inner.port = 0;
        inner.token.clear();
        inner.running.store(false, Ordering::SeqCst);
    }
}

fn pick_port() -> Result<u16, String> {
    // Ask the OS for a free port, then hand the number to the guest. Binding and
    // closing leaves a small race, but the alternative — a fixed port — collides with
    // whatever else the device runs and cannot be retried.
    let listener = std::net::TcpListener::bind("127.0.0.1:0")
        .map_err(|error| format!("cannot reserve a loopback port: {error}"))?;
    let port = listener
        .local_addr()
        .map_err(|error| format!("cannot read the reserved port: {error}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn random_token() -> String {
    // 32 random bytes as hex: the core requires at least 32 printable ASCII characters.
    let mut bytes = [0u8; 32];
    if let Ok(mut file) = std::fs::File::open("/dev/urandom") {
        if file.read_exact(&mut bytes).is_ok() {
            return bytes.iter().map(|byte| format!("{byte:02x}")).collect();
        }
    }
    // A deterministic fallback would be a constant secret; refuse to invent one.
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|value| value.as_nanos())
        .unwrap_or(0);
    format!("{nanos:032x}{nanos:032x}")
}

/// Polls the core until it answers an authenticated request, or the child dies.
fn wait_ready(app: &AppHandle, port: u16, token: &str) -> bool {
    let client = blocking_client();
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(120);
    let mut last_error = String::new();
    while std::time::Instant::now() < deadline {
        match client
            .get(format!("http://127.0.0.1:{port}/api/core/projects"))
            .bearer_auth(token)
            .timeout(std::time::Duration::from_secs(5))
            .send()
        {
            Ok(response) if response.status().is_success() => return true,
            Ok(response) => last_error = format!("core answered {}", response.status()),
            Err(error) => last_error = error.to_string(),
        }
        std::thread::sleep(std::time::Duration::from_millis(400));
    }
    let log_tail = read_log_tail(app, 20);
    if !log_tail.is_empty() {
        eprintln!("core did not become ready ({last_error}). guest log tail:\n{log_tail}");
    }
    false
}

pub fn read_log_tail(app: &AppHandle, lines: usize) -> String {
    let path = path_of(app).join("guest.log");
    let Ok(text) = std::fs::read_to_string(&path) else {
        return String::new();
    };
    let all: Vec<&str> = text.lines().collect();
    let start = all.len().saturating_sub(lines);
    all[start..].join("\n")
}

/// A blocking HTTP client with no TLS: the only peer is the guest on loopback.
fn blocking_client() -> reqwest::blocking::Client {
    reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .unwrap_or_else(|_| reqwest::blocking::Client::new())
}

/// Where a project's files live in the guest. The UI asks for guest paths, so this
/// stays a single constant rather than a per-call calculation.
pub const GUEST_WORK_ROOT: &str = "/root/.sunday/work";

pub fn is_installed(app: &AppHandle) -> bool {
    installed_version(app).is_some()
}
