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
    // Kotlin hands us `filesDir` before Tauri starts. It is the only path that is
    // certainly this app's own storage: Tauri's `app_data_dir()` resolves through the
    // same directory, but it can come back unresolved early in startup, and a relative
    // fallback would make the host look for its runtime in a directory nobody wrote to.
    if let Some(dir) = FILES_DIR.get() {
        return PathBuf::from(dir);
    }
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
}

static FILES_DIR: std::sync::OnceLock<String> = std::sync::OnceLock::new();

/// Called from Kotlin with `context.filesDir.absolutePath`.
pub fn set_files_dir(path: &str) {
    let _ = FILES_DIR.set(path.to_owned());
}

/// Where the guest sees this app's shared user data.
pub const GUEST_USERDATA: &str = "/root/.sunday";

/// The guest path for a file the host wrote into that shared directory.
///
/// user:“使用 Android SAF 桥接现有 Python Core 附件接口”+(选择的文件必须落在核心能
/// 读到的目录：宿主只做路径换算，文件本身仍在应用自己的存储里，由核心按绝对路径登记)。
///
/// Anything outside `<filesDir>/runtime/userdata` answers `None`: the core could not read
/// it, and pretending otherwise would make the attachment fail at send time instead of at
/// pick time.
pub fn guest_path(host_path: &str) -> Option<String> {
    let files = FILES_DIR.get()?;
    let root = PathBuf::from(files).join("runtime").join("userdata");
    let prefix = format!("{}/", root.to_string_lossy().trim_end_matches('/'));
    let rest = host_path.strip_prefix(&prefix)?;
    Some(format!("{GUEST_USERDATA}/{rest}"))
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
    // Versioned on purpose. A single `rootfs` directory has to be deleted before it can
    // be rewritten, and a guest that is still shutting down holds files inside it, so the
    // delete fails halfway and the install stalls on directories it cannot remove. A new
    // directory per runtime version makes an upgrade additive: write beside the old one,
    // then clean up what is no longer referenced.
    match installed_manifest(app) {
        Some(manifest) => path_of(app).join(format!("rootfs-{}", sanitise(&manifest.runtime_version))),
        None => path_of(app).join("rootfs"),
    }
}

fn installed_manifest(app: &AppHandle) -> Option<Manifest> {
    let marker = std::fs::read_to_string(marker_path(app)).ok()?;
    let value: serde_json::Value = serde_json::from_str(&marker).ok()?;
    let version = value.get("runtimeVersion")?.as_str()?.to_owned();
    let text = std::fs::read_to_string(path_of(app).join("runtime-manifest.json")).ok()?;
    let mut manifest: Manifest = serde_json::from_str(&text).ok()?;
    manifest.runtime_version = version;
    Some(manifest)
}

fn sanitise(value: &str) -> String {
    value
        .chars()
        .map(|ch| if ch.is_ascii_alphanumeric() { ch } else { '-' })
        .collect()
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
    // The archive lives in the APK's assets, which Rust cannot read as a file. Kotlin
    // stages it into filesDir/runtime and writes the manifest last; that manifest is the
    // only dependable "the bytes are here" signal, so this waits for it rather than
    // guessing at a delay.
    wait_for_stage(app)?;
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
    let file = std::fs::File::open(&archive)
        .map_err(|error| format!("cannot read the packaged runtime {}: {error}", archive.display()))?;
    let archived = file
        .metadata()
        .map_err(|error| format!("cannot stat {}: {error}", archive.display()))?
        .len();
    if manifest.rootfs_bytes > 0 && archived != manifest.rootfs_bytes {
        return Err(format!(
            "packaged runtime is {archived} bytes, manifest says {}",
            manifest.rootfs_bytes
        ));
    }

    println!("[sunday] unpacking runtime from {}", archive.display());
    // Earlier builds kept user data inside the rootfs, so replacing the runtime
    // would delete the database and the model config. Move it out once, before the
    // tree is cleared; the layout is now filesDir/runtime/userdata bound over
    // /root/.sunday.
    let userdata = path_of(app).join("userdata");
    let legacy = rootfs_dir(app).join("root/.sunday");
    if legacy.exists() && !userdata.exists() {
        if let Err(error) = copy_tree(&legacy, &userdata) {
            println!("[sunday] could not carry user data forward: {error}");
        } else {
            println!("[sunday] carried user data out of the runtime tree");
        }
    }

    let rootfs = path_of(app).join(format!("rootfs-{}", sanitise(&manifest.runtime_version)));
    if rootfs.exists() {
        std::fs::remove_dir_all(&rootfs)
            .map_err(|error| format!("cannot clear the previous runtime: {error}"))?;
    }
    std::fs::create_dir_all(&rootfs).map_err(|error| format!("cannot create the runtime dir: {error}"))?;

    // Streamed, not read into memory: the archive is ~200 MB and the extraction writes
    // ~600 MB, so holding the compressed bytes as well is how an Android process gets
    // killed halfway through an install that looked fine on a desktop.
    let decoder = flate2::read::GzDecoder::new(std::io::BufReader::new(file));
    let mut tar = tar::Archive::new(decoder);
    tar.set_preserve_permissions(true);
    tar.set_preserve_mtime(true);
    // Android refuses to change ownership as a normal app, and a `chown` failure inside
    // `tar` aborts the unpack halfway. Ownership is irrelevant here: everything is
    // already owned by this app's uid.
    tar.set_unpack_xattrs(false);
    // Unpacked entry by entry on purpose. A single file that Android refuses (an odd
    // permission bit, a name the filesystem dislikes) used to abort the whole install and
    // leave a half-written tree behind; the runtime does not need that file, and a
    // reported count is more honest than a failed install nobody can act on.
    let mut skipped = 0usize;
    let mut entries = tar
        .entries()
        .map_err(|error| format!("cannot read the runtime archive: {error}"))?;
    while let Some(next) = entries.next() {
        let mut entry = match next {
            Ok(entry) => entry,
            Err(error) => {
                skipped += 1;
                eprintln!("[sunday] archive entry unreadable: {error}");
                continue;
            }
        };
        if let Err(error) = entry.unpack_in(&rootfs) {
            skipped += 1;
            if skipped <= 5 {
                eprintln!("[sunday] skipped {}: {error}", entry.path().map(|p| p.display().to_string()).unwrap_or_default());
            }
        }
    }
    if skipped > 0 {
        println!("[sunday] unpacked the runtime with {skipped} skipped entries");
    }

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
    // The archive has done its job. Keeping it would cost the user another 200 MB for a
    // file that is never read again unless the runtime version changes.
    let _ = std::fs::remove_file(&archive);
    // Old images are only deleted once the new one works; a failed delete is not an error,
    // it just means the next launch will try again.
    if let Ok(entries) = std::fs::read_dir(path_of(app)) {
        for entry in entries.flatten() {
            let path = entry.path();
            let is_other_rootfs = path
                .file_name()
                .and_then(|name| name.to_str())
                .map(|name| name.starts_with("rootfs") && path != rootfs)
                .unwrap_or(false);
            if is_other_rootfs {
                let _ = std::fs::remove_dir_all(&path);
            }
        }
    }

    Ok(InstallState {
        installed: true,
        runtime_version: manifest.runtime_version,
        abi: manifest.abi,
        message: "installed".into(),
    })
}

/// Copies a directory tree, creating parents. Used once, to move user data out of a
/// runtime image that is about to be replaced.
fn copy_tree(from: &std::path::Path, to: &std::path::Path) -> std::io::Result<()> {
    std::fs::create_dir_all(to)?;
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let target = to.join(entry.file_name());
        let kind = entry.file_type()?;
        if kind.is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else if kind.is_file() {
            std::fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

static INSTALL_LOCK: Mutex<()> = Mutex::new(());

/// Blocks until the packaged archive has been copied out of assets.
///
/// First launch copies a few hundred megabytes; after that the manifest already exists and
/// this returns immediately. The upper bound is generous because extraction on a slow
/// device is the difference between "slow" and "broken", and a false failure would send
/// the user to a retry loop that cannot succeed any faster.
fn wait_for_stage(app: &AppHandle) -> Result<(), String> {
    let manifest = path_of(app).join("runtime-manifest.json");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(300);
    while std::time::Instant::now() < deadline {
        if manifest.exists() {
            return Ok(());
        }
        std::thread::sleep(std::time::Duration::from_millis(300));
    }
    Err("the packaged runtime was not staged within 300s".to_owned())
}

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
    /// The runtime image the running guest was started from.
    version: String,
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
                version: String::new(),
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
        // user:“Android 宿主只承担进程存活、启动和必要的连接恢复”+(所以这里先尝试连接
        // 已经在跑的那个 guest：重载界面、重建 Activity 都不能杀掉用户正在看的回合)。
        // A restart is only correct when the staged image changed underneath the guest.
        let installed = read_manifest(&self.app)
            .map(|manifest| manifest.runtime_version)
            .unwrap_or_default();
        {
            let inner = self.inner.lock().expect("runtime lock");
            if inner.child.is_some() && inner.port != 0 {
                if installed.is_empty() || inner.version == installed {
                    return Ok(inner.port);
                }
                println!(
                    "[sunday] runtime image changed {} -> {installed}, restarting the guest",
                    inner.version
                );
            }
        }
        // A guest from the previous image still holds files inside the old rootfs.
        self.stop();

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

        // proot's DT_NEEDED asks for `libtalloc.so.2`, and Gradle only packages
        // `*.so` into an APK. A copy under the name the binary asks for, in a
        // directory on LD_LIBRARY_PATH, is the loader's own mechanism for this and
        // avoids patching a maintained third-party binary.
        let shim = self
            .app
            .path()
            .app_cache_dir()
            .unwrap_or_else(|_| std::env::temp_dir())
            .join("proot-libs");
        if std::fs::create_dir_all(&shim).is_ok() {
            let source = native.join("libtalloc.so");
            let target = shim.join("libtalloc.so.2");
            if source.exists() && !target.exists() {
                let _ = std::fs::copy(&source, &target);
            }
        }
        std::fs::create_dir_all(&l2s).ok();

        // User data lives beside the runtime, never inside it: replacing the rootfs on
        // an upgrade must not take the database, config and workspace with it.
        let userdata = path_of(&self.app).join("userdata");
        std::fs::create_dir_all(&userdata).ok();
        let userdata = userdata.to_string_lossy().to_string();

        let mut argv: Vec<String> = manifest
            .launch
            .argv
            .iter()
            .map(|item| {
                item.replace("{USERDATA}", &userdata)
                    .replace("{NATIVE_LIB_DIR}", &native.to_string_lossy())
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
                    .replace("{TMP}", &tmp.to_string_lossy())
                    .replace("{SHIM}", &shim.to_string_lossy()),
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

        println!("[sunday] starting guest on port {port} rootfs={}", rootfs.display());
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
            inner.version = manifest.runtime_version.clone();
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

    /// Blocks until the guest answers an authenticated request.
    ///
    /// `ensure_started` returns as soon as proot is spawned, which is what the UI's
    /// boot screen wants but not what its first request needs: the guest spends
    /// seconds importing Python before uvicorn binds the port, so a request issued
    /// immediately after start fails with a connection error. Waiting here makes the
    /// start command mean what its name says.
    pub fn wait_ready(&self, timeout: std::time::Duration) -> Result<(), String> {
        let (port, token) = {
            let inner = self.inner.lock().expect("runtime lock");
            (inner.port, inner.token.clone())
        };
        if port == 0 {
            return Err("the guest was not started".to_owned());
        }
        let client = blocking_client();
        let deadline = std::time::Instant::now() + timeout;
        let mut last = String::new();
        while std::time::Instant::now() < deadline {
            match client
                .get(format!("http://127.0.0.1:{port}/api/core/projects"))
                .bearer_auth(&token)
                .timeout(std::time::Duration::from_secs(4))
                .send()
            {
                Ok(response) if response.status().is_success() => {
                    if let Ok(mut inner) = self.inner.lock() {
                        inner.running.store(true, Ordering::SeqCst);
                    }
                    return Ok(());
                }
                Ok(response) => last = format!("core answered {}", response.status()),
                Err(error) => last = error.to_string(),
            }
            std::thread::sleep(std::time::Duration::from_millis(300));
        }
        Err(format!("the core did not become ready: {last}"))
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
        inner.version.clear();
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
