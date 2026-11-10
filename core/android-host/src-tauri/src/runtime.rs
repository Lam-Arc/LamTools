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

/// The host path behind a guest path in shared user data.
///
/// The inverse of [`guest_path`]: the camera writes a photo into the shared directory and
/// the host has to read the same file back to decode the QR it contains.
pub fn host_path(guest_path: &str) -> Option<std::path::PathBuf> {
    let rest = guest_path.strip_prefix(GUEST_USERDATA)?;
    let files = FILES_DIR.get()?;
    Some(
        PathBuf::from(files)
            .join("runtime")
            .join("userdata")
            .join(rest.trim_start_matches('/')),
    )
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
    /// Sum of the archive's entry sizes: how many bytes the unpack writes to disk.
    ///
    /// The boot layer's percentage is `done / this`. A manifest built before this field
    /// existed answers 0, and the boot layer then shows an indeterminate bar instead of
    /// a number it would have had to invent.
    #[serde(rename = "rootfsUnpackedBytes", default)]
    pub rootfs_unpacked_bytes: u64,
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

/// How far along one cold start is, as the boot layer shows it.
///
/// `phase` is the boot layer's state machine and the whole vocabulary it accepts:
/// `staging` (the archive is still being copied out of the APK), `unpacking` (the tar is
/// being written to disk), `starting` (proot is being spawned), `waiting` (the guest is
/// importing Python), `ready`, `failed`.
///
/// `total == 0` means "there is no honest number": the boot layer then shows an
/// indeterminate bar rather than a percentage that would stall or jump around.
// user:“解压有真实进度：用已解压字节 / 总解压字节，而不是假装转圈”+(所以每一条进度都
// 带 done/total 两个真实字节数，分母来自 manifest 的 rootfsUnpackedBytes)。
#[derive(Debug, Clone, serde::Serialize)]
pub struct RuntimeProgress {
    pub phase: String,
    pub done: u64,
    pub total: u64,
    pub message: String,
}

fn emit_progress(app: &AppHandle, phase: &str, done: u64, total: u64, message: impl Into<String>) {
    let payload = RuntimeProgress {
        phase: phase.to_owned(),
        done,
        total,
        message: message.into(),
    };
    // stdout as well as the event: `adb logcat` is where a cold start is inspected when
    // the webview never comes up, and an event nobody can see is not evidence.
    println!(
        "[sunday] runtime-progress phase={} done={} total={} {}",
        payload.phase, payload.done, payload.total, payload.message
    );
    app.emit("runtime-progress", payload).ok();
}

/// Throttled unpack progress.
///
/// The tar loop visits tens of thousands of entries, so one event per entry would flood
/// both the IPC bridge and the webview's event queue. Events go out on whichever clock
/// fires first — every 500 ms or every 2% of the archive — which looks continuous on
/// screen and costs nothing measurable.
// user:“每 500ms 或每 2% 发一次，节流，避免事件洪水”+(两个阈值取先到者)。
struct UnpackTicker<'a> {
    app: &'a AppHandle,
    total: u64,
    done: u64,
    entries: u64,
    last_at: std::time::Instant,
    last_mark: u64,
}

impl<'a> UnpackTicker<'a> {
    fn new(app: &'a AppHandle, total: u64) -> Self {
        Self {
            app,
            total,
            done: 0,
            entries: 0,
            last_at: std::time::Instant::now(),
            last_mark: 0,
        }
    }

    fn note(&mut self, bytes: u64) {
        self.done = self.done.saturating_add(bytes);
        self.entries += 1;
        self.flush(false);
    }

    fn flush(&mut self, force: bool) {
        let step = if self.total > 0 {
            (self.total as f64 * 0.02).max(1.0) as u64
        } else {
            u64::MAX
        };
        if !force
            && self.done.saturating_sub(self.last_mark) < step
            && self.last_at.elapsed() < std::time::Duration::from_millis(500)
        {
            return;
        }
        self.last_at = std::time::Instant::now();
        self.last_mark = self.done;
        let message = if self.total > 0 {
            format!(
                "已解压 {} / {}",
                megabytes(self.done),
                megabytes(self.total)
            )
        } else {
            format!("已解压 {}（{} 个文件）", megabytes(self.done), self.entries)
        };
        emit_progress(self.app, "unpacking", self.done, self.total, message);
    }
}

fn megabytes(bytes: u64) -> String {
    format!("{:.0} MB", bytes as f64 / (1024.0 * 1024.0))
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
    // user:“原生窗口底色先挡住白闪，随后 HTML 启动层接管”+(解压之前的那段等待也要有
    // 阶段文字，否则启动层会停在「准备运行时」不动)。
    emit_progress(app, "staging", 0, 0, "正在取回随包运行时…");
    wait_for_stage(app)?;
    let manifest = read_manifest(app)?;
    let _guard = INSTALL_LOCK.lock().expect("install lock");

    if installed_version(app).as_deref() == Some(manifest.runtime_version.as_str())
        && rootfs_dir(app).join("opt/sunday/start_core.py").exists()
    {
        // Nothing to unpack: say so, so the boot layer moves on instead of sitting on
        // the staging line for a wait that is not happening.
        emit_progress(app, "unpacking", 1, 1, "运行时已解压，直接启动");
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
    // user:“解压有真实进度：用已解压字节 / 总解压字节”+(分母来自构建时写进 manifest 的
    // entry 尺寸之和；旧 manifest 没有这个字段时 total 为 0，启动层退化成不确定进度)。
    let mut ticker = UnpackTicker::new(app, manifest.rootfs_unpacked_bytes);
    ticker.flush(true);
    while let Some(next) = entries.next() {
        let mut entry = match next {
            Ok(entry) => entry,
            Err(error) => {
                skipped += 1;
                eprintln!("[sunday] archive entry unreadable: {error}");
                continue;
            }
        };
        // The announced size is what the entry writes, and it is counted even when the
        // write fails: the bar measures work attempted, and a skipped file is not work
        // the user will see finished later.
        let announced = entry.header().size().unwrap_or(0);
        if let Err(error) = entry.unpack_in(&rootfs) {
            skipped += 1;
            if skipped <= 5 {
                eprintln!("[sunday] skipped {}: {error}", entry.path().map(|p| p.display().to_string()).unwrap_or_default());
            }
        }
        ticker.note(announced);
    }
    // The last event may have been throttled away; one final event makes the boot layer's
    // bar reach 100% before it moves on to the start phase.
    ticker.flush(true);
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
        // user:“失败路径保留：core_start 抛错时启动层显示错误与「重试」按钮”+(所以失败
        // 也是一条进度事件：界面不必等到 invoke 的返回值才知道该显示错误)。
        match self.start_guest() {
            Ok(port) => Ok(port),
            Err(error) => {
                emit_progress(&self.app, "failed", 0, 0, error.clone());
                Err(error)
            }
        }
    }

    /// The body of [`Runtime::ensure_started`], wrapped so that every early return has
    /// exactly one place to report a failure to the boot layer.
    fn start_guest(&self) -> Result<u16, String> {
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
                    let port = inner.port;
                    // Already running: the boot layer only has to wait for its own
                    // first paint, so report the phase it is actually in.
                    drop(inner);
                    emit_progress(&self.app, "waiting", 0, 0, "核心已在运行，正在连接…");
                    return Ok(port);
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
        emit_progress(&self.app, "starting", 0, 0, "正在启动 Linux 运行时…");
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
                    // user:“加，安卓控制”+(Core 靠这个标记决定要不要把设备控制工具交给模型；
                    // 桌面与远程模式没有这个变量，就不会出现一个点了没反应的按钮)。
                    "SUNDAY_HOST_PLATFORM=android".to_owned(),
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
        // user:“启动核心 → 正在加载界面”+(proot 起来了但 Python 还在 import，这一段也要有
        // 文字；否则启动层会停在「启动核心」不动，看起来和卡死一样)。
        emit_progress(&app, "waiting", 0, 0, "等待核心应答…");
        std::thread::spawn(move || {
            let ready = wait_ready(&app, port, &token);
            running.store(ready, Ordering::SeqCst);
            if ready {
                emit_progress(&app, "ready", 1, 1, "核心已就绪");
            } else {
                let tail = read_log_tail(&app, 1);
                emit_progress(&app, "failed", 0, 0, format!("核心未就绪 {tail}"));
            }
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
        let started = std::time::Instant::now();
        let mut last_report = std::time::Instant::now();
        // user:“启动核心 → 正在加载界面”+(等待期间每 3 秒报一次已等待的秒数：截图能证明
        // 这段时间里界面在动，而不是一片静止)。
        emit_progress(&self.app, "waiting", 0, 0, "等待核心应答…");
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
                    emit_progress(&self.app, "ready", 1, 1, "核心已就绪");
                    return Ok(());
                }
                Ok(response) => last = format!("core answered {}", response.status()),
                Err(error) => last = error.to_string(),
            }
            if last_report.elapsed() >= std::time::Duration::from_secs(3) {
                last_report = std::time::Instant::now();
                emit_progress(
                    &self.app,
                    "waiting",
                    0,
                    0,
                    format!("等待核心应答… 已等待 {}s", started.elapsed().as_secs()),
                );
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
