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

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri::Emitter;

/// 一台已经连上这台电脑的设备。
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct PeerInfo {
    pub id: String,
    pub name: String,
    /// `direct` / `relay` / `unknown`。
    pub path: String,
    /// 当前选中路径的往返延迟（毫秒）；0 表示还没测出来。
    pub rtt_ms: u64,
    /// 这条连接上真的收到过 `initialize`。
    pub session: bool,
    /// 连上来的时间（Unix 秒）：当前那台断开时，用它挑一台还在线的当当前。
    pub since: u64,
}

/// 连上来的设备名册 + 现在正在用哪一台。
///
/// user:“设备切换：多设备时切换当前连接，状态随之更新（不要出现「切换了但状态还显示旧
/// 设备」）”+(状态只认 `current()`：谁的路经、谁的会话、谁的名字都从它取，不会出现
/// 「切换了但徽标/会话还是上一台」)。
#[derive(Debug, Default)]
pub struct DeviceBook {
    peers: std::collections::BTreeMap<String, PeerInfo>,
    current: Option<String>,
}

impl DeviceBook {
    /// 一台设备连上来。
    ///
    /// 已经有当前设备时不抢焦点：另一台的自动重连不该把用户正在用的那台换掉；还没人
    /// 在用（第一次扫码）时，它就是当前。
    pub fn connect(&mut self, id: &str, name: &str, path: &str, now: u64) {
        let peer = self
            .peers
            .entry(id.to_owned())
            .or_insert_with(|| PeerInfo {
                id: id.to_owned(),
                name: name.to_owned(),
                path: path.to_owned(),
                rtt_ms: 0,
                session: false,
                since: now,
            });
        if !name.is_empty() {
            peer.name = name.to_owned();
        }
        peer.path = path.to_owned();
        // 新连接还没 `initialize`：上一台的「会话已恢复」不能算到这一台上。
        peer.session = false;
        if self.current.is_none() {
            self.current = Some(id.to_owned());
        }
    }

    /// 一条连接收掉了。
    pub fn close(&mut self, id: &str) {
        self.peers.remove(id);
        if self.current.as_deref() == Some(id) {
            // 当前那台断了：退到还在线里最近连上的一台，而不是留一个指向空记录的 id。
            self.current = self
                .peers
                .values()
                .max_by_key(|peer| peer.since)
                .map(|peer| peer.id.clone());
        }
    }

    /// 这条连接真的收到 `initialize` 了。
    pub fn session(&mut self, id: &str) {
        if let Some(peer) = self.peers.get_mut(id) {
            peer.session = true;
        }
    }

    /// 这条连接的路经变了（打洞成功 / 退回中继）。
    pub fn path_changed(&mut self, id: &str, path: &str, rtt_ms: u64) {
        if let Some(peer) = self.peers.get_mut(id) {
            peer.path = path.to_owned();
            peer.rtt_ms = rtt_ms;
        }
    }

    /// 切换当前设备。切换不存在的设备要当场失败，而不是留一个空当前。
    pub fn switch(&mut self, id: &str) -> bool {
        if self.peers.contains_key(id) {
            self.current = Some(id.to_owned());
            true
        } else {
            false
        }
    }

    pub fn current(&self) -> Option<&PeerInfo> {
        self.current
            .as_deref()
            .and_then(|id| self.peers.get(id))
    }

    pub fn current_id(&self) -> Option<String> {
        self.current.clone()
    }

    pub fn list(&self) -> Vec<PeerInfo> {
        self.peers.values().cloned().collect()
    }

    pub fn is_empty(&self) -> bool {
        self.peers.is_empty()
    }

    pub fn len(&self) -> usize {
        self.peers.len()
    }
}

/// Core 探测的短 TTL 缓存。
///
/// user:“p2p_status 每次全量探测 Core（阻塞上限 ~2 秒）→ 加短 TTL 缓存（例如 1–2 秒）”+
/// (缓存只挡高频重复问：换了端口、或者超过 TTL 就重新真探一次，绝不把旧的「就绪」当成
/// 现在的实话)。
#[derive(Debug)]
pub struct ProbeCache {
    ttl: std::time::Duration,
    port: u16,
    at: Option<std::time::Instant>,
    state: CoreState,
}

impl Default for ProbeCache {
    fn default() -> Self {
        Self {
            ttl: std::time::Duration::from_millis(1500),
            port: 0,
            at: None,
            state: CoreState::Unknown,
        }
    }
}

impl ProbeCache {
    pub fn with_ttl(ttl: std::time::Duration) -> Self {
        Self {
            ttl,
            ..Self::default()
        }
    }

    /// 还在有效期内就返回上一次的结论。
    pub fn get(&self, port: u16, now: std::time::Instant) -> Option<CoreState> {
        let at = self.at?;
        if port == 0 || port != self.port {
            return None;
        }
        if now.saturating_duration_since(at) <= self.ttl {
            Some(self.state)
        } else {
            None
        }
    }

    pub fn put(&mut self, port: u16, state: CoreState, now: std::time::Instant) {
        self.port = port;
        self.at = Some(now);
        self.state = state;
    }

    /// 明确知道 Core 变了（重启、换端口）：立刻作废旧结论。
    pub fn invalidate(&mut self) {
        self.at = None;
        self.state = CoreState::Unknown;
    }
}

/// 一次文件互传的进度（宿主转给界面，字段与 `transfer::Progress` 一致）。
#[derive(Debug, Clone)]
pub struct TransferInfo {
    pub id: String,
    pub direction: String,
    pub name: String,
    pub total: u64,
    pub transferred: u64,
    pub percent: u8,
    pub state: String,
    pub code: String,
    pub message: String,
    pub path: String,
    /// 本机源文件的绝对路径（只有本端发起的传输才有）。
    ///
    /// user:“失败可重试”+(传输进程只说「发到对方哪里」，不重复说「从本机哪个文件来」；
    /// 源路径只有发起方知道，宿主在起发送进程时记下来，界面重试时才不用再让用户选一次文件)。
    pub source: String,
}

/// 一个已经落盘的文件（接收端事实）。
#[derive(Debug, Clone)]
pub struct ReceivedFile {
    pub transfer_id: String,
    pub path: String,
    pub name: String,
    pub size: u64,
    pub peer: String,
    pub from: String,
    pub at: u64,
}

/// 互传名册：最近那些传输的进度 + 已经收到的文件。
///
/// user:“发送与接收都要有可观察进度”“收到文件后落盘、登记为 artifact 条目，并给出
/// 「打开预览/所在文件夹」的入口”+(界面要看到「正在传/传失败了/传完了在哪」；宿主只做
/// 记录与转述，不去猜传输层在干什么——进度是传输进程说的事实)。
#[derive(Debug, Default)]
pub struct TransferBook {
    transfers: Vec<TransferInfo>,
    received: Vec<ReceivedFile>,
}

/// 名册最多留多少条（不清空会一直长，用户也不需要上个月的每一块进度）。
const TRANSFER_HISTORY: usize = 40;

impl TransferBook {
    /// 同一条传输收到新进度就原地更新，不重复堆行。
    pub fn progress(&mut self, info: TransferInfo) {
        if let Some(slot) = self.transfers.iter_mut().find(|item| item.id == info.id) {
            *slot = info;
            return;
        }
        if self.transfers.len() >= TRANSFER_HISTORY {
            self.transfers.remove(0);
        }
        self.transfers.push(info);
    }

    /// 落盘事实：同一个路径只记一次（同一条状态行可能被重放）。
    pub fn received(&mut self, file: ReceivedFile) {
        if self.received.iter().any(|item| item.path == file.path) {
            return;
        }
        if self.received.len() >= TRANSFER_HISTORY {
            self.received.remove(0);
        }
        self.received.push(file);
    }

    /// 最近的传输（新的在后）。
    pub fn transfers(&self) -> Vec<TransferInfo> {
        self.transfers.clone()
    }

    /// 用户取消了一条传输：本地这一行当场落到「已取消」，不必等传输进程的超时。
    ///
    /// user:“支持取消”+(取消是正常结局，不是失败：码用 `file_cancelled`，界面据此标成
    /// 中性色；真正的停机由调用方负责终止发送进程，这里只记事实)。
    pub fn cancel(&mut self, id: &str) -> bool {
        let Some(slot) = self.transfers.iter_mut().find(|item| item.id == id) else {
            return false;
        };
        slot.state = "cancelled".to_owned();
        slot.code = "file_cancelled".to_owned();
        slot.message = "已取消".to_owned();
        slot.percent = slot.percent.min(100);
        true
    }

    /// 这条传输还在跑吗（宿主据此决定「重复取消」是不是无事可做）。
    pub fn is_active(&self, id: &str) -> bool {
        self.transfers
            .iter()
            .find(|item| item.id == id)
            .map(|item| item.state == "offered" || item.state == "transferring")
            .unwrap_or(false)
    }

    /// 收到的文件（新的在前，界面直接拿来列表展示）。
    pub fn files(&self) -> Vec<ReceivedFile> {
        let mut files = self.received.clone();
        files.reverse();
        files
    }
}

// user:“三项全做”+(配对码和失效时间作为一份状态同时写入和读取)。
#[derive(Clone, Default)]
struct PairingCode {
    ticket: String,
    expires_at: u64,
    revision: u64,
}

type PairingCodeSlot = Arc<(Mutex<PairingCode>, Condvar)>;

fn publish_pairing_code(slot: &PairingCodeSlot, ticket: String, expires_at: u64) {
    let mut code = slot.0.lock().unwrap_or_else(|error| error.into_inner());
    if code.ticket != ticket || code.expires_at != expires_at {
        let revision = code.revision + 1;
        *code = PairingCode { ticket, expires_at, revision };
        slot.1.notify_all();
    }
}

#[derive(Clone, Default)]
pub struct P2pHostState {
    child: Arc<Mutex<Option<Child>>>,
    startup: Arc<Mutex<()>>,
    pairing_code: PairingCodeSlot,
    port: Arc<Mutex<u16>>,
    /// 连上来的设备名册：谁在线、当前用哪一台、各自走直连还是中继。
    ///
    /// user:“我根本不知道卡在哪里了”“设备切换：多设备时切换当前连接，状态随之更新”+
    /// (以前只有一个「当前手机」的 `Option<String>`：第二台连上来界面还是显示第一台，
    /// 切换之后会话与路径也还挂在旧设备上。名册把「谁在线」与「现在用哪台」分开记)。
    devices: Arc<Mutex<DeviceBook>>,
    /// 互传名册：进度与已收到的文件（界面靠它显示「传到哪了」「文件在哪」）。
    ///
    /// user:“发送与接收都要有可观察进度”“收到文件后给出打开预览/所在文件夹的入口”+
    /// (传输进程只在状态通道上说事实，宿主把它收进名册给界面用，不在界面自己算)。
    transfers: Arc<Mutex<TransferBook>>,
    /// 最近一次启动传输进程用的后端地址：进程死掉之后照它重启。
    api_base: Arc<Mutex<String>>,
    core_address: Arc<Mutex<String>>,
    /// 守护线程已经起来（一个进程只要一条）。
    supervisord: Arc<AtomicBool>,
    /// 宿主正在退出：守护线程不要再拉起新进程。
    stopping: Arc<AtomicBool>,
    /// 同一张票据的二维码只生成一次（每次生成都要起一次子进程）。
    qr_cache: Arc<Mutex<(String, String)>>,
    /// 最近一次启动失败的原因。
    ///
    /// user:“缺失或启动失败时给明确错误（用户可读），不得表现为「远程连接默默不可用」”+
    /// (以前失败只写进日志，界面上就是一张空白页；现在把原因留在状态里，设备页直接显示)。
    error: Arc<Mutex<Option<String>>>,
    /// 状态通道解析失败的原因：坏了就明说，不静默退回旧状态。
    ///
    /// user:“SESSION 依赖解析子进程 stdout 文本（弱契约）→ 改为结构化状态通道（或至少
    /// 加版本前缀 + 解析失败即明确报错，不要静默）”+(传输进程发来的结构化行坏掉时，
    /// 界面要能看到「状态通道坏了」，而不是继续显示上一次的旧状态)。
    protocol_error: Arc<Mutex<Option<String>>>,
    /// Core 探测的短 TTL 缓存：界面高频取状态时不再每次都真去连一次 Core。
    ///
    /// user:“p2p_status 每次全量探测 Core（阻塞上限 ~2 秒）→ 加短 TTL 缓存（例如 1–2 秒），
    /// 避免高频轮询把 UI 拖慢”+(一次探测最多要等 800ms 连接 + 1200ms 读；界面一秒钟问几次，
    /// 就是几次真实 TCP 连接，Core 忙的时候整页都在等它)。
    probe: Arc<Mutex<ProbeCache>>,
    /// 上一次广播过的阶段：只在真的变了才发，避免每 3 秒刷一条噪声。
    ///
    /// user:“配对/连接/恢复会话分阶段可见”“扫码后立刻有反馈”+(以前界面在监听
    /// `p2p-progress`，但宿主从来没发过；扫码之后只能等 3 秒轮询，看不出卡在配对
    /// 还是连 Core)。
    last_phase: Arc<Mutex<String>>,
    /// 本端正在跑的「发送」子进程（同一时刻只允许一个：传输是顺序的）。
    ///
    /// user:“支持取消”+(取消在本端就是让发送进程停下来；发送进程是宿主起的，
    /// 只有宿主手里有它的句柄，所以句柄必须留在状态里，不能扔在命令的栈上)。
    send_child: Arc<Mutex<Option<(String, Child)>>>,
    send_requests: Arc<Mutex<std::collections::VecDeque<OutgoingTransfer>>>,
}

#[derive(Clone)]
struct OutgoingTransfer {
    id: String,
    source: PathBuf,
    ticket: String,
    name: String,
}

impl P2pHostState {
    fn pairing_code(&self) -> PairingCode {
        self.pairing_code
            .0
            .lock()
            .unwrap_or_else(|error| error.into_inner())
            .clone()
    }

    fn pairing_code_snapshot(&self, running: bool) -> PairingCode {
        let code = self.pairing_code();
        if running {
            code
        } else {
            PairingCode {
                revision: code.revision,
                ..PairingCode::default()
            }
        }
    }
}

fn data_dir() -> PathBuf {
    let base = std::env::var("APPDATA")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::temp_dir());
    base.join("Sunday").join("p2p")
}

/// 用户是否开着「远程访问」。
///
/// user:“记住用户是否开启远程访问（持久化，不依赖临时状态）”+(开关不能只活在这个进程的
/// 内存里：重启 Sunday 之后，用户上次开着就该继续开着，上次关掉就不该偷偷起来)。
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Prefs {
    #[serde(default)]
    pub auto_connect: bool,
}

impl Default for Prefs {
    fn default() -> Self {
        Self {
            auto_connect: false,
        }
    }
}

fn prefs_path() -> PathBuf {
    data_dir().join("p2p-prefs.json")
}

pub fn read_prefs() -> Prefs {
    let path = prefs_path();
    let Ok(text) = std::fs::read_to_string(&path) else {
        return Prefs::default();
    };
    serde_json::from_str(&text).unwrap_or_default()
}

fn write_prefs(prefs: &Prefs) -> Result<(), String> {
    let dir = data_dir();
    std::fs::create_dir_all(&dir).map_err(|error| format!("无法创建配置目录：{error}"))?;
    let text = serde_json::to_string_pretty(prefs).map_err(|error| error.to_string())?;
    std::fs::write(prefs_path(), text).map_err(|error| format!("无法保存远程访问开关：{error}"))
}

/// Core 这一层的状态。
///
/// user:“面对『对方 Core 没响应』时必须降级显示”+(桌面自己不链 `sunday-p2p` crate，
/// 因为 iroh 的 wmi 依赖与桌面冲突，所以这里只留最小的等价状态)。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CoreState {
    Unknown,
    Ready,
    Down,
}

impl CoreState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Ready => "ready",
            Self::Down => "down",
        }
    }
}

/// 1.5 秒内问一次 `GET /api/health`：有 200 就算就绪。
///
/// user:“Core 无响应时必须降级显示，不能继续显示正常”+(进程被杀、端口换了、卡住了，
/// 都表现为「没有应答」；探测必须有超时，否则界面自己先卡住)。
pub fn probe_core(port: u16) -> CoreState {
    use std::io::{Read, Write};
    use std::net::{TcpStream, ToSocketAddrs};

    if port == 0 {
        return CoreState::Unknown;
    }
    let address = match ("127.0.0.1", port).to_socket_addrs() {
        Ok(mut addrs) => match addrs.next() {
            Some(address) => address,
            None => return CoreState::Down,
        },
        Err(_) => return CoreState::Down,
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, std::time::Duration::from_millis(800))
    else {
        return CoreState::Down;
    };
    let _ = stream.set_read_timeout(Some(std::time::Duration::from_millis(1200)));
    let _ = stream.set_write_timeout(Some(std::time::Duration::from_millis(1200)));
    let request = "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
    if stream.write_all(request.as_bytes()).is_err() {
        return CoreState::Down;
    }
    let mut buffer = [0u8; 64];
    match stream.read(&mut buffer) {
        Ok(read) if read > 0 => {
            let head = String::from_utf8_lossy(&buffer[..read]);
            if head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200") {
                CoreState::Ready
            } else {
                CoreState::Down
            }
        }
        _ => CoreState::Down,
    }
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
///
/// 结果同时记进状态：成功清掉旧错误，失败留一条用户能读的原因。
///
/// user:“发布版本启动后 P2P 服务能真的起来：给出启动状况的可见状态（运行/未运行/失败原因）”
/// +(调用方只要能读到状态就行，不必各自再记一遍)。
fn ensure_child(api_base: &str, state: &P2pHostState, manual: bool) -> Result<(String, u16), String> {
    let _startup = state
        .startup
        .lock()
        .map_err(|_| "传输进程状态不可用".to_owned())?;
    if manual {
        state.stopping.store(false, Ordering::SeqCst);
    } else if state.stopping.load(Ordering::SeqCst) {
        return Err("已停止远程访问".to_owned());
    }
    let ready_address = state.core_address.lock().unwrap_or_else(|error| error.into_inner()).clone();
    let address = if ready_address.is_empty() { api_base } else { &ready_address };
    let result = ensure_child_once(address, state);
    if let Ok(mut slot) = state.error.lock() {
        *slot = result.as_ref().err().cloned();
    }
    result
}

fn ensure_child_once(api_base: &str, state: &P2pHostState) -> Result<(String, u16), String> {
    {
        let mut guard = state.child.lock().map_err(|_| "传输进程状态不可用".to_string())?;
        if let Some(child) = guard.as_mut() {
            if child
                .try_wait()
                .map_err(|error| format!("无法读取传输进程状态：{error}"))?
                .is_none()
            {
                let ticket = state.pairing_code().ticket;
                let port = *state.port.lock().map_err(|_| "端口不可用".to_string())?;
                return Ok((ticket, port));
            }
            *guard = None;
        }
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
    // user:“桌面端收到文件后落盘到约定目录（例如 <lam_home>/received/<日期>/）”+(传输进程
    // 的数据目录是 `<lam_home>/p2p`，接收目录固定放在 `<lam_home>/received`：用户在同一个
    // 位置就能找到别人发来的文件，不必去猜进程把东西放哪了)。
    let received_root = dir
        .parent()
        .map(|base| base.join("received"))
        .unwrap_or_else(|| dir.join("received"));

    let mut command = Command::new(binary()?);
    command
        .arg("serve")
        .arg("--dir")
        .arg(&dir)
        .arg("--receive")
        .arg(&received_root)
        .arg("--name")
        .arg(name)
        .arg("--core-port")
        .arg(port.to_string())
        .arg("--core-token")
        .arg(core_token)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn().map_err(|error| format!("启动传输进程失败：{error}"))?;

    let log_path = data_dir().join("p2p.log");
    if let Some(stderr) = child.stderr.take() {
        spawn_log_reader(
            log_path.clone(),
            BufReader::new(stderr),
            None,
            None,
            None,
            None,
            None,
        );
    }
    let startup = child
        .stdout
        .take()
        .ok_or_else(|| "传输进程没有输出".to_owned())
        .and_then(|stdout| {
            let (send, receive) = mpsc::sync_channel(1);
            std::thread::spawn(move || {
                let mut reader = BufReader::new(stdout);
                let result = read_transport_startup(&mut reader).map(|code| (reader, code));
                let _ = send.send(result);
            });
            wait_for_transport_startup(receive, &state.stopping, Duration::from_secs(30))
        });
    let (reader, PairingCode { ticket, expires_at, .. }) = match startup {
        Ok(startup) => startup,
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
    };
    publish_pairing_code(&state.pairing_code, ticket.clone(), expires_at);
    if let Ok(mut slot) = state.port.lock() {
        *slot = port;
    }
    if let Ok(mut slot) = state.api_base.lock() {
        *slot = api_base.trim().to_owned();
    }

    // 继续读传输进程的输出：网络变化会打一行新的 TICKET，配对失败时会有 PEER 和错误。
    // user:“连不上……一点反应都没有”+(排障需要证据；之前 READY 之后就不再读管道，
    // 对端是否连到、中继是否可用全都丢了)。
    let ticket_slot = Arc::clone(&state.pairing_code);
    let devices_slot = Arc::clone(&state.devices);
    let protocol_slot = Arc::clone(&state.protocol_error);
    let transfers_slot = Arc::clone(&state.transfers);
    spawn_log_reader(
        log_path,
        reader,
        Some(ticket_slot),
        Some(devices_slot),
        Some(protocol_slot),
        Some(transfers_slot),
        // `serve` 不是为某一个文件起的：接收侧的进度本来就没有源文件。
        None,
    );
    *state.child.lock().unwrap_or_else(|error| error.into_inner()) = Some(child);
    // 进程起来之后交给守护线程：它死了（崩溃、被系统收掉）就照原来的地址重启，
    // 否则手机要等到用户手动打开「设备连接」才能重新连上。
    supervise(state);
    Ok((ticket, port))
}

// user:“修完之后，去找远程连接/跨网通信/跨设备使用中最不稳定/问题最大的地方 修掉，并列出候选”+
// (等待就绪与读取子进程输出分开，静默或只输出半行都不能卡住桌面)。
fn wait_for_transport_startup<T>(
    receive: mpsc::Receiver<Result<T, String>>,
    stopping: &AtomicBool,
    timeout: Duration,
) -> Result<T, String> {
    let deadline = Instant::now() + timeout;
    loop {
        if stopping.load(Ordering::SeqCst) {
            return Err("已停止远程访问".to_owned());
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err("远程访问启动超时，请检查网络或中继设置后重试".to_owned());
        }
        match receive.recv_timeout(remaining.min(Duration::from_millis(100))) {
            Ok(result) => return result,
            Err(mpsc::RecvTimeoutError::Timeout) => {}
            Err(mpsc::RecvTimeoutError::Disconnected) => {
                return Err("传输进程在就绪前退出".to_owned());
            }
        }
    }
}

fn read_transport_startup(reader: &mut impl BufRead) -> Result<PairingCode, String> {
    let mut code = PairingCode::default();
    for line in reader.lines() {
        let line = line.map_err(|error| format!("无法读取传输进程启动状态：{error}"))?;
        let line = line.trim();
        if line == "READY" {
            return if code.ticket.is_empty() {
                Err("传输进程没有给出配对码".to_owned())
            } else {
                Ok(code)
            };
        }
        match sunday_p2p_status::parse_line(line) {
            Some(Ok(sunday_p2p_status::StatusEvent::Ticket { ticket, expires_at })) => {
                code.ticket = ticket;
                code.expires_at = expires_at;
            }
            // user:“p2p 与 relay 的稳定性核查，并按需优化”+(把中继配置错误送回桌面，方便直接修正)。
            Some(Ok(sunday_p2p_status::StatusEvent::StartupFailed { message })) => return Err(message),
            _ => {
                if let Some(ticket) = line.strip_prefix("TICKET ") {
                    code.ticket = ticket.to_owned();
                } else if let Some(expiry) = line.strip_prefix("EXPIRES ") {
                    code.expires_at = expiry.parse().unwrap_or(0);
                }
            }
        }
    }
    Err("传输进程在就绪前退出".to_owned())
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
        if let Err(error) = ensure_child(&api, &host, false) {
            eprintln!("[sunday] p2p supervisor: {error}");
        }
    });
}

/// 把子进程的后续输出写进 `%APPDATA%/Sunday/p2p/p2p.log`，同时把状态收进宿主。
///
/// user:“SESSION 依赖解析子进程 stdout 文本（弱契约）→ 改为结构化状态通道（或至少加版本
/// 前缀 + 解析失败即明确报错，不要静默）”+(带版本前缀的结构化行是唯一契约；旧格式的自由
/// 文本仍然认，那是为了兼容已经在跑的老进程。结构化行坏了就写一条明确的错误进状态，
/// 不静默把上一次的旧状态继续显示下去)。
fn spawn_log_reader(
    path: PathBuf,
    mut reader: BufReader<impl std::io::Read + Send + 'static>,
    ticket: Option<PairingCodeSlot>,
    devices: Option<Arc<Mutex<DeviceBook>>>,
    protocol_error: Option<Arc<Mutex<Option<String>>>>,
    transfers: Option<Arc<Mutex<TransferBook>>>,
    // 这个进程是本端为哪一个本机文件起的（只有 `send` 子命令才有）。
    source: Option<String>,
) {
    std::thread::spawn(move || {
        use std::io::Write;
        let mut file = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
            .ok();
        let mut line = String::new();
        let mut legacy_ticket = None;
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    let trimmed = line.trim();
                    if trimmed.is_empty() {
                        continue;
                    }
                    match sunday_p2p_status::parse_line(trimmed) {
                        // 结构化行是权威：字段名固定，不再靠切空格。
                        Some(Ok(event)) => apply_status_event(
                            event,
                            ticket.as_ref(),
                            devices.as_ref(),
                            transfers.as_ref(),
                            source.as_deref(),
                        ),
                        // user:“解析失败即明确报错，不要静默”+(这一行看起来是状态行却坏了：
                        // 记一条用户能读的错误，并把原始行留给日志)。
                        Some(Err(error)) => {
                            let message = format!("状态通道解析失败：{error}");
                            eprintln!("[sunday] {message} :: {trimmed}");
                            if let Some(slot) = &protocol_error {
                                if let Ok(mut current) = slot.lock() {
                                    *current = Some(message);
                                }
                            }
                        }
                        // 不是状态行：按旧格式认（老进程还在打这些）。
                        None => {
                            if let Some(value) = trimmed.strip_prefix("TICKET ") {
                                legacy_ticket = Some(value.to_owned());
                            } else if let Some(value) = trimmed.strip_prefix("EXPIRES ") {
                                if let (Some(slot), Some(code), Ok(expiry)) =
                                    (ticket.as_ref(), legacy_ticket.take(), value.parse())
                                {
                                    publish_pairing_code(slot, code, expiry);
                                }
                            } else {
                                apply_legacy_line(trimmed, devices.as_ref());
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

/// 收下一条结构化状态。
fn apply_status_event(
    event: sunday_p2p_status::StatusEvent,
    ticket: Option<&PairingCodeSlot>,
    devices: Option<&Arc<Mutex<DeviceBook>>>,
    transfers: Option<&Arc<Mutex<TransferBook>>>,
    source: Option<&str>,
) {
    use sunday_p2p_status::StatusEvent;
    match event {
        StatusEvent::Ticket {
            ticket: value,
            expires_at,
        } => {
            if let Some(slot) = ticket {
                publish_pairing_code(slot, value, expires_at);
            }
            audit("ticket", json!({ "expiresAt": expires_at }));
        }
        StatusEvent::Peer {
            peer,
            name,
            trusted,
            path,
        } => {
            // 没被接受的连接不进名册：它不是「在线设备」。
            if !trusted {
                return;
            }
            let path = if path.is_empty() {
                "unknown".to_owned()
            } else {
                path
            };
            audit("peer", json!({ "id": &peer, "name": &name, "path": &path }));
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    book.connect(&peer, &name, &path, now_secs());
                }
            }
        }
        StatusEvent::PeerClosed { peer, reason } => {
            audit("peer_closed", json!({ "id": &peer, "reason": &reason }));
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    book.close(&peer);
                }
            }
        }
        StatusEvent::Session { peer } => {
            audit("session", json!({ "id": &peer }));
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    book.session(&peer);
                }
            }
        }
        StatusEvent::Path {
            peer,
            path,
            rtt_ms,
        } => {
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    book.path_changed(&peer, &path, rtt_ms);
                }
            }
        }
        // user:“发送与接收都要有可观察进度”+(传输进程说的进度原样收进名册；界面不再
        // 自己按字节数算百分比，也不会出现「界面说传完了、传输进程还在写」)。
        StatusEvent::Transfer {
            transfer_id,
            direction,
            name,
            total,
            transferred,
            percent,
            state,
            code,
            message,
            path,
        } => {
            if let Some(book) = transfers {
                if let Ok(mut book) = book.lock() {
                    book.progress(TransferInfo {
                        id: transfer_id,
                        direction,
                        name,
                        total,
                        transferred,
                        percent,
                        state,
                        code,
                        message,
                        path,
                        // 只有本端发起的进程会带源文件；接收侧的进度没有这一项。
                        source: source.unwrap_or_default().to_owned(),
                    });
                }
            }
        }
        // user:“收到文件后落盘到约定目录，登记为 artifact 条目，并给出「打开预览/所在
        // 文件夹」的入口”+(宿主把落盘事实收进名册，界面用绝对路径打开预览或所在文件夹；
        // 资料库登记由界面按这条事实调用既有的 library 动作，不在这里另写一套)。
        StatusEvent::Received {
            transfer_id,
            path,
            name,
            size,
            peer,
            from,
        } => {
            audit("received", json!({ "transferId": &transfer_id, "path": &path, "from": &from }));
            if let Some(book) = transfers {
                if let Ok(mut book) = book.lock() {
                    book.received(ReceivedFile {
                        transfer_id,
                        path,
                        name,
                        size,
                        peer,
                        from,
                        at: now_secs(),
                    });
                }
            }
        }
        // 这些由别的字段承载（票据过期时间、中继摘要、Core 事实），这里不额外记。
        StatusEvent::Relay { .. } | StatusEvent::Core { .. } | StatusEvent::StartupFailed { .. } => {}
    }
}

/// 旧格式自由文本（兼容已经在跑的老传输进程）。
///
/// 老进程只打 `PEER <id> trusted=true` 这种行，没有名字也没有路径；能认出多少算多少，
/// 认不出的行当日志留在文件里。
fn apply_legacy_line(
    trimmed: &str,
    devices: Option<&Arc<Mutex<DeviceBook>>>,
) {
    let (kind, rest) = match trimmed.split_once(' ') {
        Some((kind, rest)) => (kind, rest),
        None => (trimmed, ""),
    };
    let mut parts = rest.split_whitespace();
    let peer = parts.next().unwrap_or("").to_owned();
    if peer.is_empty() {
        return;
    }
    let trusted = !rest.contains("trusted=false");
    let path = rest
        .split_whitespace()
        .find_map(|token| token.strip_prefix("path="))
        .unwrap_or("")
        .to_owned();
    match kind {
        "PEER" => {
            if !trusted {
                return;
            }
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    let path = if path.is_empty() {
                        "unknown".to_owned()
                    } else {
                        path
                    };
                    book.connect(&peer, "", &path, now_secs());
                }
            }
        }
        "PEER-CLOSED" | "PEER-ERROR" | "PEER-REJECTED" => {
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    book.close(&peer);
                }
            }
        }
        // user:“只有业务真正可用才显示「已连接电脑」”+(真的收到 initialize 才算会话恢复；
        // 老进程也打这一行，所以老进程下这条判定同样成立)。
        "SESSION" => {
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    book.session(&peer);
                }
            }
        }
        "PATH" => {
            if let Some(book) = devices {
                if let Ok(mut book) = book.lock() {
                    // 旧格式没有 RTT，保持 0，不拿旧值冒充新测量。
                    book.path_changed(&peer, &path, 0);
                }
            }
        }
        _ => {}
    }
}

/// 现在（Unix 秒）：设备名册用它排出「最近连上的一台」。
fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0)
}

/// 一条审计记录：JSON Lines，时间戳 + 稳定事件名 + 字段。
fn audit_record(event: &str, fields: Value, at: u64) -> Value {
    json!({ "at": at, "event": event, "fields": fields })
}

/// user:“审计远程访问、授权和拒绝操作”+(追加写 `p2p-audit.jsonl`；票据只记过期时间，
/// 不把可用的配对票写进日志)。
fn audit(event: &str, fields: Value) {
    let record = audit_record(event, fields, now_secs());
    let path = data_dir().join("p2p-audit.jsonl");
    use std::io::Write as _;
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let _ = writeln!(file, "{record}");
    }
}

/// The text the phone pastes. Starts the transport on first use.
///
/// 异步命令：启动要等中继和 READY（最长 30 秒），不能把 IPC 线程堵在那里让整个窗口没反应。
#[tauri::command]
pub async fn p2p_ticket(
    api_base: String,
    renew: Option<bool>,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    let host = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let (_, port) = ensure_child(&api_base, &host, true)?;
        // user:“三项全做”+(本次启动和换码不修改开机选项，只有显式设置才写入偏好)。
        let code = if renew == Some(true) {
            renew_pairing_code(&host)?
        } else {
            host.pairing_code()
        };
        Ok(json!({ "ticket": code.ticket, "expiresAt": code.expires_at, "pairingCodeRevision": code.revision, "port": port }))
    })
    .await
    .map_err(|error| error.to_string())?
}

fn renew_pairing_code(state: &P2pHostState) -> Result<PairingCode, String> {
    let mut child = state.child.lock().map_err(|_| "传输进程状态不可用".to_owned())?;
    let code = state.pairing_code.0.lock().unwrap_or_else(|error| error.into_inner());
    let previous = code.ticket.clone();
    let stdin = child.as_mut().and_then(|child| child.stdin.as_mut())
        .ok_or_else(|| "无法向传输服务请求新配对码".to_owned())?;
    writeln!(stdin, "renew-ticket").map_err(|error| format!("无法请求新配对码：{error}"))?;
    drop(child);
    let (code, _) = state.pairing_code.1
        .wait_timeout_while(code, std::time::Duration::from_secs(5), |code| code.ticket == previous)
        .unwrap_or_else(|error| error.into_inner());
    if code.ticket.is_empty() || code.ticket == previous {
        return Err("传输服务未返回新配对码，请重试".to_owned());
    }
    Ok(code.clone())
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
    tauri::async_runtime::spawn_blocking(move || ensure_child(&api_base, &host, true))
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
    let _startup = state.startup.lock().unwrap_or_else(|error| error.into_inner());
    state.stopping.store(true, Ordering::SeqCst);
    stop_transport(state);
}

fn stop_transport(state: &P2pHostState) {
    if let Ok(mut guard) = state.child.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
    publish_pairing_code(&state.pairing_code, String::new(), 0);
    // user:“设备切换：多设备时切换当前连接”+(停止之后名册必须清空：留着上一批设备，
    // 下次启动第一眼就显示成「有设备在线」)。
    if let Ok(mut book) = state.devices.lock() {
        *book = DeviceBook::default();
    }
    if let Ok(mut protocol) = state.protocol_error.lock() {
        *protocol = None;
    }
    if let Ok(mut probe) = state.probe.lock() {
        probe.invalidate();
    }
    // user:“只有业务真正可用才显示「已连接电脑」”+(停止之后不能留着上一台的
    // 「会话已恢复」；名册整体清空已经包含这一条)。

    if let Ok(mut phase) = state.last_phase.lock() {
        phase.clear();
    }
    if let Ok(mut error) = state.error.lock() {
        *error = None;
    }
    if let Ok(mut api) = state.api_base.lock() {
        api.clear();
    }
    if let Ok(mut cache) = state.qr_cache.lock() {
        cache.0.clear();
        cache.1.clear();
    }
}

// user:“全部处理并继续寻找”+(由本机 Core 发布新地址驱动恢复，设备页无需在线或轮询)。
pub fn core_ready(state: &P2pHostState, api_base: &str) {
    *state.core_address.lock().unwrap_or_else(|error| error.into_inner()) = api_base.to_owned();
    let _startup = state.startup.lock().unwrap_or_else(|error| error.into_inner());
    let previous = state.api_base.lock().unwrap_or_else(|error| error.into_inner()).clone();
    if !needs_core_rebind(state.stopping.load(Ordering::SeqCst), &previous, api_base) {
        return;
    }
    stop_transport(state);
    // 守护线程在新地址启动失败时也能继续恢复。
    *state.api_base.lock().unwrap_or_else(|error| error.into_inner()) = api_base.to_owned();
    let result = ensure_child_once(api_base, state);
    *state.error.lock().unwrap_or_else(|error| error.into_inner()) = result.err();
}

fn needs_core_rebind(stopped: bool, current: &str, ready: &str) -> bool {
    !stopped && !current.is_empty() && current != ready
}

#[test]
fn a_new_core_port_rebinds_only_an_enabled_service() {
    let old = "http://127.0.0.1:8787";
    let new = "http://127.0.0.1:8788";
    assert!(needs_core_rebind(false, old, new));
    assert!(!needs_core_rebind(true, old, new));
    assert!(!needs_core_rebind(false, "", new));
    assert!(!needs_core_rebind(false, new, new));
}

#[tauri::command]
pub fn p2p_serve_stop(state: tauri::State<'_, P2pHostState>) -> Result<Value, String> {
    stop(state.inner());
    // user:“三项全做”+(停止本次访问，不覆盖用户单独保存的开机选项)。
    Ok(json!({ "serving": false, "autoConnect": read_prefs().auto_connect }))
}

/// 状态查询：顺带把 Core 探一次，必要时把传输进程挪到新端口。
///
/// user:“只有业务真正可用才显示「已连接电脑」；Core 无响应时必须降级显示”+(所以这里
/// 返回的不是一个 `connected` 布尔，而是四层事实与一句原因：传输进程在不在、有没有设备
/// 认证过、Core 通不通、会话有没有真的恢复)。
#[tauri::command]
pub async fn p2p_status(
    app: tauri::AppHandle,
    api_base: Option<String>,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    let mut running = false;
    if let Ok(mut guard) = state.child.lock() {
        if let Some(child) = guard.as_mut() {
            running = child.try_wait().ok().flatten().is_none();
        }
    }
    let PairingCode { ticket, expires_at, revision } = state.pairing_code_snapshot(running);
    let (current, peers) = {
        let book = state.devices.lock().unwrap_or_else(|slot| slot.into_inner());
        (book.current().cloned(), book.list())
    };
    let error = state.error.lock().ok().and_then(|slot| slot.clone());
    let protocol_error = state.protocol_error.lock().ok().and_then(|slot| slot.clone());

    let wanted = api_base
        .as_deref()
        .and_then(|value| url::Url::parse(value.trim()).ok())
        .and_then(|parsed| parsed.port());
    let started_port = *state.port.lock().unwrap_or_else(|slot| slot.into_inner());

    // user:“p2p_status 每次全量探测 Core（阻塞上限 ~2 秒）→ 加短 TTL 缓存”+(1.5 秒内
    // 复用上一次结论；换端口或超时就重新真探——旧结论只能是「刚看过」，不能变成常驻)。
    // user:“三项全做”+(状态更新为了取新配对码时，用正在服务的 Core 判定已有连接)。
    let probe_port = (running && !peers.is_empty() && started_port != 0)
        .then_some(started_port)
        .or(wanted);
    let core = match probe_port {
        Some(port) => probe_cached_async(state.inner().clone(), port).await,
        None => CoreState::Unknown,
    };
    let peer_connected = !peers.is_empty();
    // user:“只有业务真正可用才显示「已连接电脑」”+(会话恢复只看当前那台：切换之后
    // 判定跟着换，不会出现「切换了但状态还显示旧设备」)。
    let current_session = current.as_ref().map(|peer| peer.session).unwrap_or(false);
    let session_resumed = peer_connected && core == CoreState::Ready && current_session;
    let (view, reason) = derive_view(running, peer_connected, core, session_resumed, error.is_some());
    // user:“配对/连接/恢复会话分阶段可见”“扫码后立刻有反馈”+(阶段变化马上推给界面，
    // 不用等下一轮轮询；只在真的变了才发，避免刷屏)。
    let changed = match state.last_phase.lock() {
        Ok(mut last) => {
            if last.as_str() != view {
                *last = view.to_owned();
                true
            } else {
                false
            }
        }
        Err(_) => false,
    };
    if changed {
        let _ = app.emit("p2p-progress", json!({ "phase": view, "reason": reason }));
    }
    let now = now_secs();
    // 传输程序在哪：找不到时 `binary()` 会给一句用户能读的原因，正好当状态显示。
    let (binary_path, binary_error) = match binary() {
        Ok(path) => (path.to_string_lossy().to_string(), Value::Null),
        Err(reason) => (String::new(), json!(reason)),
    };
    let current_id = current.as_ref().map(|peer| peer.id.clone());
    let device_list: Vec<Value> = peers
        .iter()
        .map(|peer| {
            json!({
                "id": peer.id,
                "name": peer.name,
                "path": peer.path,
                "rttMs": peer.rtt_ms,
                "session": peer.session,
                "current": current_id.as_deref() == Some(peer.id.as_str()),
            })
        })
        .collect();
    Ok(json!({
        // running 是「进程在跑」；serving 保留给老调用方，含义相同。
        "running": running,
        "serving": running,
        "ticket": ticket,
        "expiresAt": expires_at,
        "pairingCodeRevision": revision,
        "expiresIn": expires_at.saturating_sub(now),
        // connected 保留给旧界面（= 有设备在线）；新界面请看 view / layers。
        "connected": peer_connected,
        // peer 是「当前那台」；多设备时用它，不再含糊地表示「有设备」。
        "peer": current_id,
        "deviceName": current.as_ref().map(|peer| peer.name.clone()).unwrap_or_default(),
        // user:“真实路径显示：区分直连/中继，默认放在连接详情里”+(当前那台此刻走的路)。
        "path": current.as_ref().map(|peer| peer.path.clone()).unwrap_or_else(|| "unknown".to_owned()),
        "rttMs": current.as_ref().map(|peer| peer.rtt_ms).unwrap_or(0),
        "auditLog": data_dir().join("p2p-audit.jsonl").to_string_lossy(),
        "devices": device_list,
        // user:“电脑显示待确认设备，用户确认配对”+(扫码只登记申请；这里给界面
        // 一份待确认名册，确认后才写可信名单)。
        "pending": pending_devices(),
        // user:“只有业务真正可用才显示已连接”+(view 是唯一权威：connected/degraded/connecting/
        // waiting/offline；reason 是一句原因的稳定标识)。
        "view": view,
        "reason": reason,
        "layers": {
            "transport": running,
            "device": if peer_connected { "authenticated" } else { "unpaired" },
            "core": core.as_str(),
            "session": if session_resumed { "resumed" } else { "not_resumed" },
        },
        "autoConnect": read_prefs().auto_connect,
        // user:“缺失或启动失败时给明确错误（用户可读）”+(null 表示没问题)。
        "error": error,
        // user:“解析失败即明确报错，不要静默”+(状态通道坏了就显示原因，别装作一切正常)。
        "protocolError": protocol_error,
        "binary": binary_path,
        "binaryError": binary_error,
    }))
}

/// 带短 TTL 缓存的 Core 探测（异步命令里用：探测本身是阻塞的，必须离开异步执行器）。
async fn probe_cached_async(state: P2pHostState, port: u16) -> CoreState {
    if port == 0 {
        return CoreState::Unknown;
    }
    if let Ok(cache) = state.probe.lock() {
        if let Some(cached) = cache.get(port, std::time::Instant::now()) {
            return cached;
        }
    }
    let probed = tauri::async_runtime::spawn_blocking(move || probe_core(port))
        .await
        .unwrap_or(CoreState::Down);
    if let Ok(mut cache) = state.probe.lock() {
        cache.put(port, probed, std::time::Instant::now());
    }
    probed
}

/// 同上，同步版本：宿主自己的推送线程用它（已经在普通线程里，不需要 spawn_blocking）。
fn probe_blocking_cached(state: &P2pHostState, port: u16) -> CoreState {
    if port == 0 {
        return CoreState::Unknown;
    }
    if let Ok(cache) = state.probe.lock() {
        if let Some(cached) = cache.get(port, std::time::Instant::now()) {
            return cached;
        }
    }
    let probed = probe_core(port);
    if let Ok(mut cache) = state.probe.lock() {
        cache.put(port, probed, std::time::Instant::now());
    }
    probed
}

/// 切换当前设备。
///
/// user:“设备切换：多设备时切换当前连接，状态随之更新（不要出现「切换了但状态还显示旧
/// 设备」）”+(名册里的 `current` 是唯一真相：切完再取一次状态，peer / path / session /
/// 名字全部跟着换，不需要界面自己记一份「当前是谁」)。
#[tauri::command]
pub fn p2p_switch_device(
    id: String,
    state: tauri::State<'_, P2pHostState>,
) -> Result<Value, String> {
    let mut book = state
        .devices
        .lock()
        .map_err(|_| "设备名册不可用".to_string())?;
    if !book.switch(&id) {
        return Err("这台设备现在没有连接".to_owned());
    }
    let current = book.current().cloned();
    Ok(json!({
        "currentDevice": current.as_ref().map(|peer| peer.id.clone()),
        "name": current.as_ref().map(|peer| peer.name.clone()).unwrap_or_default(),
        "path": current
            .as_ref()
            .map(|peer| peer.path.clone())
            .unwrap_or_else(|| "unknown".to_owned()),
        "session": current.as_ref().map(|peer| peer.session).unwrap_or(false),
    }))
}

/// 手机回到前台时的恢复快照。
///
/// user:“Android 前后台恢复（本仓库只有桌面侧；手机宿主不在本仓库）→ 桌面侧把「恢复所需
/// 的状态与接口」准备好并在文档写清手机侧该怎么接”+(手机切后台再回来时，需要知道：传输
/// 还在不在、票据还有多久、当前是哪台、走的是直连还是中继、会话恢复没恢复。一次取全比连问
/// 五次稳，也不会出现「问到一半状态变了」的拼接)。
#[tauri::command]
pub fn p2p_resume_state(state: tauri::State<'_, P2pHostState>) -> Result<Value, String> {
    let mut running = false;
    if let Ok(mut guard) = state.child.lock() {
        if let Some(child) = guard.as_mut() {
            running = child.try_wait().ok().flatten().is_none();
        }
    }
    let (current, peers) = {
        let book = state.devices.lock().unwrap_or_else(|slot| slot.into_inner());
        (book.current().cloned(), book.list())
    };
    let PairingCode { ticket, expires_at, .. } = state.pairing_code_snapshot(running);
    let port = *state.port.lock().unwrap_or_else(|slot| slot.into_inner());
    let now = now_secs();
    let prefs = read_prefs();
    Ok(json!({
        // 接口自报版本：手机宿主据此决定怎么解释这份快照。
        "protocol": "sunday.p2p.resume.v1",
        "serverTime": now,
        "transport": {
            "running": running,
            "port": port,
            "ticket": ticket,
            "expiresAt": expires_at,
            "expiresIn": expires_at.saturating_sub(now),
            "autoConnect": prefs.auto_connect,
        },
        "current": current.as_ref().map(|peer| json!({
            "id": peer.id,
            "name": peer.name,
            "path": peer.path,
            "session": peer.session,
        })),
        "devices": peers.iter().map(|peer| json!({
            "id": peer.id,
            "name": peer.name,
            "path": peer.path,
            "session": peer.session,
        })).collect::<Vec<Value>>(),
        // user:“不确定送达时先查询状态，不盲目重发”+(手机侧恢复时必须先按幂等键查一遍
        // 悬着的写，再决定重发；这条契约写进文档，也在这里给出它需要的会话上下文)。
        "reconcile": {
            "requires": "thread/resume",
            "hint": "恢复后先用 client_message_id 查日志，再重发",
        },
    }))
}

/// 状态变化推给界面：界面不再自己定时轮询。
///
/// user:“清理无效轮询与监听：把托盘/状态面板里的定时轮询收敛到事件驱动，避免常驻空转”+
/// (这里是宿主内部一个 2 秒节拍：快照没变就什么都不发，没人连的时候也不去探 Core；
/// 界面那边因此一个定时器都不用，页面关掉就没有任何唤醒)。
pub fn start_emitter(app: tauri::AppHandle, state: P2pHostState) {
    std::thread::spawn(move || {
        let mut last = String::new();
        loop {
            std::thread::sleep(std::time::Duration::from_secs(2));
            let snapshot = snapshot_now(&state);
            let text = snapshot.to_string();
            if text == last {
                continue;
            }
            last = text;
            let _ = app.emit("p2p-state", snapshot);
        }
    });
}

/// 现在这一刻给界面看的快照（只在真的变了才被推出去）。
fn snapshot_now(state: &P2pHostState) -> Value {
    let mut running = false;
    if let Ok(mut guard) = state.child.lock() {
        if let Some(child) = guard.as_mut() {
            running = child.try_wait().ok().flatten().is_none();
        }
    }
    let (current, peers) = {
        let book = state.devices.lock().unwrap_or_else(|slot| slot.into_inner());
        (book.current().cloned(), book.list())
    };
    let PairingCode { expires_at, revision, .. } = state.pairing_code_snapshot(running);
    let error = state.error.lock().ok().and_then(|slot| slot.clone());
    // 没人连的时候不探 Core：空转时一次端口连接都不该有。
    let core = if peers.is_empty() || !running {
        CoreState::Unknown
    } else {
        let port = *state.port.lock().unwrap_or_else(|slot| slot.into_inner());
        probe_blocking_cached(state, port)
    };
    let current_session = current.as_ref().map(|peer| peer.session).unwrap_or(false);
    let session_resumed = !peers.is_empty() && core == CoreState::Ready && current_session;
    let (view, reason) = derive_view(running, !peers.is_empty(), core, session_resumed, error.is_some());
    let now = now_secs();
    let current_id = current.as_ref().map(|peer| peer.id.clone());
    // user:“发送与接收都要有可观察进度”“收到文件后给出打开预览/所在文件夹的入口”+
    // (界面直接读这两份名册：transfers 是「正在传/刚传完/为什么失败」，received 是
    // 「文件落在哪个路径」；宿主不替传输层猜，只转述它说过的事实)。
    let (transfers, received) = {
        let book = state
            .transfers
            .lock()
            .unwrap_or_else(|slot| slot.into_inner());
        let transfers: Vec<Value> = book
            .transfers()
            .into_iter()
            .map(|item| {
                json!({
                    "id": item.id,
                    "direction": item.direction,
                    "name": item.name,
                    "total": item.total,
                    "transferred": item.transferred,
                    "percent": item.percent,
                    "state": item.state,
                    "code": item.code,
                    "message": item.message,
                    "path": item.path,
                    // 本机源文件：界面「重试」用它再发一次，不必让用户重新选文件。
                    "source": item.source,
                })
            })
            .collect();
        let received: Vec<Value> = book
            .files()
            .into_iter()
            .map(|file| {
                json!({
                    "transferId": file.transfer_id,
                    "path": file.path,
                    "name": file.name,
                    "size": file.size,
                    "peer": file.peer,
                    "from": file.from,
                    "at": file.at,
                })
            })
            .collect();
        (transfers, received)
    };
    json!({
        "running": running,
        "connected": !peers.is_empty(),
        "peer": current_id,
        "deviceName": current.as_ref().map(|peer| peer.name.clone()).unwrap_or_default(),
        "path": current.as_ref().map(|peer| peer.path.clone()).unwrap_or_else(|| "unknown".to_owned()),
        "rttMs": current.as_ref().map(|peer| peer.rtt_ms).unwrap_or(0),
        // user:“三项全做”+(通过状态通知页面换码，具体配对码和有效期一次读取)。
        "pairingCodeRevision": revision,
        "expiresIn": expires_at.saturating_sub(now),
        "view": view,
        "reason": reason,
        "error": error,
        "devices": peers.iter().map(|peer| json!({
            "id": peer.id,
            "name": peer.name,
            "path": peer.path,
            "rttMs": peer.rtt_ms,
            "session": peer.session,
            "current": current_id.as_deref() == Some(peer.id.as_str()),
        })).collect::<Vec<Value>>(),
        "pending": pending_devices(),
        // 传输进度与落盘名册：界面据此画进度条、给「打开预览/所在文件夹」的入口。
        "transfers": transfers,
        "received": received,
    })
}

/// 把四层事实折成给界面看的结论与一句原因。
///
/// user:“只有业务真正可用才显示「已连接电脑」；Core 无响应时必须降级显示”+(判定只有
/// 一份、且是纯函数：隧道在、设备在、Core 死掉时必须是 degraded 而不是 connected)。
fn derive_view(
    running: bool,
    peer_connected: bool,
    core: CoreState,
    session_resumed: bool,
    failed: bool,
) -> (&'static str, &'static str) {
    if !running {
        return ("offline", if failed { "start_failed" } else { "offline" });
    }
    if !peer_connected {
        return ("waiting", "no_device");
    }
    match core {
        CoreState::Down => ("degraded", "core_unavailable"),
        CoreState::Unknown => ("connecting", "-"),
        CoreState::Ready if !session_resumed => ("connecting", "session_not_resumed"),
        CoreState::Ready => ("connected", "-"),
    }
}

/// 起一次「发送到设备」。
///
/// user:“发送入口：…选中后开始传输”+(桌面宿主不链 `sunday-p2p` crate（iroh 的 windows
/// 依赖与桌面冲突），所以发送是让宿主起一个 `sunday-p2p send` 进程：进度走同一套结构化
/// 状态通道，直接进 `p2p_status.transfers[]`，界面不需要第二条通道)。
#[tauri::command]
pub fn p2p_send_file(
    state: tauri::State<'_, P2pHostState>,
    path: String,
    ticket: String,
    name: Option<String>,
) -> Result<Value, String> {
    if path.trim().is_empty() {
        return Err("没有选中文件".to_owned());
    }
    start_file_transfer(state.inner(), OutgoingTransfer {
        id: outgoing_transfer_id()?,
        source: PathBuf::from(path.trim()),
        ticket,
        name: name.unwrap_or_default(),
    })
}

fn outgoing_transfer_id() -> Result<String, String> {
    let mut nonce = [0u8; 16];
    getrandom::fill(&mut nonce).map_err(|error| format!("无法生成传输编号：{error}"))?;
    Ok(nonce.iter().map(|byte| format!("{byte:02x}")).collect())
}

// user:“全部处理并继续寻找”+(重试沿用原传输编号与原接收设备，当前选择的设备不参与重试)。
#[tauri::command]
pub fn p2p_retry_transfer(state: tauri::State<'_, P2pHostState>, id: String) -> Result<Value, String> {
    let mut transfer = state.send_requests.lock().map_err(|_| "发送记录不可用".to_owned())?
        .iter().find(|transfer| transfer.id == id).cloned()
        .ok_or_else(|| "找不到原发送记录，请从文件重新发送".to_owned())?;
    if state.transfers.lock().is_ok_and(|book| {
        book.transfers.iter().any(|row| row.id == id && row.state == "cancelled")
    }) {
        transfer.id = outgoing_transfer_id()?;
    }
    start_file_transfer(state.inner(), transfer)
}

fn start_file_transfer(state: &P2pHostState, transfer: OutgoingTransfer) -> Result<Value, String> {
    let source = &transfer.source;
    if !source.is_file() {
        return Err("找不到这个文件（可能已经被移动或删除）".to_owned());
    }
    if transfer.ticket.trim().is_empty() {
        return Err("缺少对方的地址票，先在「设备连接」里重新扫码配对".to_owned());
    }
    // 上限与传输层一致（8 GiB）：先在这里拦，省得起了进程再失败。
    let size = std::fs::metadata(&source).map(|meta| meta.len()).unwrap_or(0);
    if size > 8 * 1024 * 1024 * 1024 {
        return Err("文件超过单文件 8 GiB 上限，请先分割".to_owned());
    }
    let dir = data_dir();
    std::fs::create_dir_all(&dir).ok();
    let mut slot = state.send_child.lock().map_err(|_| "发送进程状态不可用".to_owned())?;
    if let Some((_, existing)) = slot.as_mut() {
        if existing.try_wait().map_err(|error| format!("无法读取发送状态：{error}"))?.is_none() {
            return Err("已有文件正在发送，请等待完成或取消后重试".to_owned());
        }
    }
    let mut command = Command::new(binary()?);
    command
        .arg("send")
        .arg("--dir")
        .arg(&dir)
        .arg("--ticket")
        .arg(transfer.ticket.trim())
        .arg("--transfer-id")
        .arg(&transfer.id)
        .arg("--file")
        .arg(&source);
    let requested = transfer.name.trim();
    if !requested.trim().is_empty() {
        command.arg("--as").arg(requested.trim());
    }
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command
        .spawn()
        .map_err(|error| format!("启动发送进程失败：{error}"))?;
    let source_text = source.to_string_lossy().to_string();
    if let Some(stdout) = child.stdout.take() {
        spawn_log_reader(
            dir.join("p2p-send.log"),
            BufReader::new(stdout),
            None,
            None,
            None,
            Some(Arc::clone(&state.transfers)),
            // 源文件跟着这一条进度走：界面「重试」才知道该重发哪一个。
            Some(source_text.clone()),
        );
    }
    // stderr 也必须有人读：管道写满会把子进程卡住。
    if let Some(stderr) = child.stderr.take() {
        spawn_log_reader(
            dir.join("p2p-send.log"),
            BufReader::new(stderr),
            None,
            None,
            None,
            None,
            None,
        );
    }
    *slot = Some((transfer.id.clone(), child));
    let result = json!({
        "started": true,
        "transferId": transfer.id,
        "source": source_text,
        "name": source
            .file_name()
            .and_then(|item| item.to_str())
            .map(|item| if requested.trim().is_empty() { item.to_owned() } else { requested.trim().to_owned() })
            .unwrap_or_default(),
    });
    let mut requests = state.send_requests.lock().unwrap_or_else(|error| error.into_inner());
    requests.retain(|request| request.id != transfer.id);
    requests.push_back(transfer);
    if requests.len() > 128 {
        requests.pop_front();
    }
    Ok(result)
}

/// 取消一条传输。
///
/// user:“支持取消”+(本端不想再传了：停掉发送进程，并把名册里这一行落到「已取消」，
/// 不必等传输层 180 秒的空闲超时；取消是正常结局，码用 `file_cancelled`)。
#[tauri::command]
pub fn p2p_cancel_transfer(
    state: tauri::State<'_, P2pHostState>,
    id: String,
) -> Result<Value, String> {
    // user:“全修”+(接收方取消交给持有部分文件的进程处理，等它推送取消结果)。
    if state.transfers.lock().is_ok_and(|book| {
        book.transfers.iter().any(|row| row.id == id && row.direction == "receive")
            && book.is_active(&id)
    }) {
        let mut child = state.child.lock().map_err(|_| "传输进程状态不可用".to_owned())?;
        let stdin = child.as_mut().and_then(|child| child.stdin.as_mut())
            .ok_or_else(|| "接收服务已停止，无法取消这笔传输".to_owned())?;
        let id_json = serde_json::to_string(&id).map_err(|error| error.to_string())?;
        writeln!(stdin, "cancel-receive {id_json}").map_err(|error| format!("未能取消接收：{error}"))?;
        return Ok(json!({ "requested": true, "id": id }));
    }
    let mut stopped = false;
    if let Ok(mut slot) = state.send_child.lock() {
        if let Some((_, child)) = slot.as_mut().filter(|(active, _)| active == &id) {
            let _ = child.kill();
            let _ = child.wait();
            stopped = true;
            *slot = None;
        }
    }
    let recorded = stopped && state
        .transfers
        .lock()
        .map(|mut book| book.cancel(&id))
        .unwrap_or(false);
    Ok(json!({ "cancelled": recorded || stopped, "id": id }))
}

/// 在系统文件管理器里定位一个文件。
///
/// user:“完成后可「打开所在文件夹」”+(路径可能是接收目录里的文件，也可能是本机源文件；
/// 只认存在的绝对路径，免得打开一个空目录还装作成功)。
#[tauri::command]
pub fn p2p_reveal_path(path: String) -> Result<Value, String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("没有可定位的路径".to_owned());
    }
    let target = PathBuf::from(trimmed);
    if !target.is_absolute() {
        return Err("只能定位本机的绝对路径".to_owned());
    }
    if !target.exists() {
        return Err("这个位置已经没有文件了（可能被移动或删除）".to_owned());
    }
    #[cfg(target_os = "windows")]
    {
        // user:“启动后台任务时会弹命令行窗，能不能隐藏掉？”+(定位文件用的 explorer 同样是
        // 子进程，不许闪黑窗；这里只改窗口显示，参数与失败判定都不动)。
        let mut command = Command::new("explorer");
        command.arg("/select,").arg(&target);
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        }
        command
            .spawn()
            .map_err(|error| format!("打开文件管理器失败：{error}"))?;
    }
    #[cfg(target_os = "macos")]
    {
        Command::new("open")
            .arg("-R")
            .arg(&target)
            .spawn()
            .map_err(|error| format!("打开访达失败：{error}"))?;
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let folder = target
            .parent()
            .map(|item| item.to_path_buf())
            .unwrap_or_else(|| target.clone());
        Command::new("xdg-open")
            .arg(folder)
            .spawn()
            .map_err(|error| format!("打开文件管理器失败：{error}"))?;
    }
    Ok(json!({ "revealed": true, "path": trimmed }))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn transfer(id: &str, percent: u8, state: &str) -> TransferInfo {
        TransferInfo {
            id: id.to_owned(),
            direction: "receive".to_owned(),
            name: "a.txt".to_owned(),
            total: 100,
            transferred: percent as u64,
            percent,
            state: state.to_owned(),
            code: String::new(),
            message: String::new(),
            path: String::new(),
            source: String::new(),
        }
    }

    /// 取消要把名册里那一行落到「已取消」，并且保留源文件（界面据此才敢给「重试」）。
    ///
    /// user:“支持取消；失败可重试”+(取消是正常结局不是失败：码是 `file_cancelled`；
    /// 但重试需要源路径，所以取消不能把这一行删掉)。
    #[test]
    fn cancelling_marks_the_row_and_keeps_the_source() {
        let mut book = TransferBook::default();
        let mut info = transfer("t-9", 42, "transferring");
        info.direction = "send".to_owned();
        info.source = "C:/work/a.bin".to_owned();
        book.progress(info);
        assert!(book.is_active("t-9"), "刚 offer 的传输算在跑");

        assert!(book.cancel("t-9"));
        let row = &book.transfers()[0];
        assert_eq!(row.state, "cancelled");
        assert_eq!(row.code, "file_cancelled");
        assert_eq!(row.source, "C:/work/a.bin");
        assert!(!book.is_active("t-9"), "取消之后不该还占着「在跑」");

        // 不存在的 id 不当作成功，避免界面显示「已取消」却什么都没变。
        assert!(!book.cancel("missing"));
    }

    /// user:“发送与接收都要有可观察进度”+(同一条传输的新进度要覆盖旧的，不能越堆越长：
    /// 界面只该看到「现在到哪了」，而不是十条历史百分比)。
    #[test]
    fn transfer_progress_updates_in_place() {
        let mut book = TransferBook::default();
        book.progress(transfer("t-1", 10, "transferring"));
        book.progress(transfer("t-1", 90, "transferring"));
        assert_eq!(book.transfers().len(), 1);
        assert_eq!(book.transfers()[0].percent, 90);
        book.progress(transfer("t-2", 5, "transferring"));
        assert_eq!(book.transfers().len(), 2);
    }

    /// user:“收到文件后落盘、给出打开预览/所在文件夹的入口”+(落盘事实按路径去重、新的在前：
    /// 同一条状态行重放不会在列表里出现两个同样的文件)。
    #[test]
    fn a_received_file_is_listed_once_and_newest_first() {
        let mut book = TransferBook::default();
        let file = |path: &str| ReceivedFile {
            transfer_id: "t-1".to_owned(),
            path: path.to_owned(),
            name: "a.txt".to_owned(),
            size: 3,
            peer: "node".to_owned(),
            from: "手机".to_owned(),
            at: 1,
        };
        book.received(file("C:/recv/a.txt"));
        book.received(file("C:/recv/a.txt"));
        book.received(file("C:/recv/b.txt"));
        let files = book.files();
        assert_eq!(files.len(), 2, "同一路径只能记一次");
        assert_eq!(files[0].path, "C:/recv/b.txt", "新收到的排在最前");
    }

    /// user:“设备切换：多设备时切换当前连接，状态随之更新（不要出现「切换了但状态还显示
    /// 旧设备」）”+(状态只从「当前那台」取：切换之后会话与路径立刻换成新设备)。
    #[test]
    fn switching_devices_moves_every_layer_to_the_new_one() {
        let mut book = DeviceBook::default();
        book.connect("phone-a", "A 手机", "direct", 100);
        book.session("phone-a");
        book.connect("phone-b", "B 手机", "relay", 200);
        // 第二台连上来不抢当前：用户还在用 A。
        assert_eq!(book.current_id().as_deref(), Some("phone-a"));
        assert_eq!(book.current().map(|peer| peer.session), Some(true));
        // 切到 B：路径与会话都必须是 B 的（B 还没 initialize -> false）。
        assert!(book.switch("phone-b"));
        assert_eq!(book.current_id().as_deref(), Some("phone-b"));
        assert_eq!(book.current().map(|peer| peer.path.as_str()), Some("relay"));
        assert_eq!(book.current().map(|peer| peer.session), Some(false));
        // 切不存在的设备要当场失败，不能留一个空当前。
        assert!(!book.switch("phone-z"));
        assert_eq!(book.current_id().as_deref(), Some("phone-b"));
    }

    /// 当前那台断了要退到还在线的一台；不是当前的那台断了不能影响当前。
    #[test]
    fn closing_the_current_device_falls_back_to_one_still_online() {
        let mut book = DeviceBook::default();
        book.connect("phone-a", "A", "direct", 100);
        book.connect("phone-b", "B", "direct", 200);
        book.close("phone-b");
        assert_eq!(book.current_id().as_deref(), Some("phone-a"));
        book.close("phone-a");
        assert_eq!(book.current_id(), None);
        assert!(book.is_empty());
    }

    /// 一台老设备重连不该把「会话已恢复」带到新连接上。
    #[test]
    fn a_reconnect_starts_without_a_resumed_session() {
        let mut book = DeviceBook::default();
        book.connect("phone-a", "A", "direct", 100);
        book.session("phone-a");
        book.connect("phone-a", "A", "relay", 200);
        let current = book.current().expect("still there");
        assert!(!current.session, "新连接还没 initialize");
        assert_eq!(current.path, "relay");
    }

    /// user:“SESSION 依赖解析子进程 stdout 文本（弱契约）→ 改为结构化状态通道”+
    /// (结构化行落进名册：字段从 JSON 里来，不靠切空格)。
    #[test]
    fn a_structured_peer_and_session_line_reaches_the_device_book() {
        let book = std::sync::Arc::new(Mutex::new(DeviceBook::default()));
        let trusted = sunday_p2p_status::StatusEvent::Peer {
            peer: "node-1".to_owned(),
            name: "我的手机".to_owned(),
            trusted: true,
            path: "direct".to_owned(),
        };
        apply_status_event(trusted, None, Some(&book), None, None);
        {
            let book = book.lock().unwrap();
            let current = book.current().expect("peer 进了名册");
            assert_eq!(current.name, "我的手机");
            assert_eq!(current.path, "direct");
            assert!(!current.session);
        }
        apply_status_event(
            sunday_p2p_status::StatusEvent::Session {
                peer: "node-1".to_owned(),
            },
            None,
            Some(&book),
            None,
            None,
        );
        assert!(book.lock().unwrap().current().unwrap().session);
        apply_status_event(
            sunday_p2p_status::StatusEvent::Path {
                peer: "node-1".to_owned(),
                path: "relay".to_owned(),
                rtt_ms: 42,
            },
            None,
            Some(&book),
            None,
            None,
        );
        assert_eq!(book.lock().unwrap().current().unwrap().path, "relay");
        assert_eq!(book.lock().unwrap().current().unwrap().rtt_ms, 42);
        apply_status_event(
            sunday_p2p_status::StatusEvent::PeerClosed {
                peer: "node-1".to_owned(),
                reason: String::new(),
            },
            None,
            Some(&book),
            None,
            None,
        );
        assert!(book.lock().unwrap().is_empty());
    }

    /// 没被接受的连接不算在线设备（否则界面上会冒出一台根本用不了的机器）。
    #[test]
    fn a_rejected_connection_never_enters_the_book() {
        let book = std::sync::Arc::new(Mutex::new(DeviceBook::default()));
        apply_status_event(
            sunday_p2p_status::StatusEvent::Peer {
                peer: "node-1".to_owned(),
                name: "被撤销的手机".to_owned(),
                trusted: false,
                path: String::new(),
            },
            None,
            Some(&book),
            None,
            None,
        );
        assert!(book.lock().unwrap().is_empty());
    }

    /// 老格式的行仍然认（兼容已经在跑的老进程），路径与名字没有就留空/unknown。
    #[test]
    fn legacy_lines_still_reach_the_book() {
        let book = std::sync::Arc::new(Mutex::new(DeviceBook::default()));
        apply_legacy_line("PEER node-9 trusted=true", Some(&book));
        assert_eq!(book.lock().unwrap().current_id().as_deref(), Some("node-9"));
        apply_legacy_line("SESSION node-9", Some(&book));
        assert!(book.lock().unwrap().current().unwrap().session);
        apply_legacy_line("PEER-ERROR node-9 boom", Some(&book));
        assert!(book.lock().unwrap().is_empty());
    }

    /// user:“p2p_status 每次全量探测 Core（阻塞上限 ~2 秒）→ 加短 TTL 缓存”+
    /// (1.5 秒内复用；超时、换端口都要重新真探，旧结论不能变成常驻)。
    #[test]
    fn the_core_probe_is_cached_only_for_a_moment() {
        let mut cache = ProbeCache::with_ttl(std::time::Duration::from_millis(1500));
        let start = std::time::Instant::now();
        assert_eq!(cache.get(8080, start), None, "没探过就没有结论");
        cache.put(8080, CoreState::Ready, start);
        assert_eq!(
            cache.get(8080, start + std::time::Duration::from_millis(500)),
            Some(CoreState::Ready)
        );
        assert_eq!(
            cache.get(8080, start + std::time::Duration::from_millis(1600)),
            None,
            "超过 TTL 必须重新真探"
        );
        assert_eq!(
            cache.get(9090, start),
            None,
            "换了端口就不能拿旧端口的结论冒充"
        );
        cache.invalidate();
        assert_eq!(cache.get(8080, start + std::time::Duration::from_millis(1)), None);
    }

    /// user:“只有业务真正可用才显示「已连接电脑」”+(四层齐了才是 connected)。
    #[test]
    fn only_a_fully_working_stack_is_connected() {
        assert_eq!(
            derive_view(true, true, CoreState::Ready, true, false),
            ("connected", "-")
        );
    }

    /// user:“Core 无响应时必须降级显示，不能继续显示正常”+(隧道和手机都还在也不行)。
    #[test]
    fn a_dead_core_degrades_instead_of_claiming_connected() {
        assert_eq!(
            derive_view(true, true, CoreState::Down, false, false),
            ("degraded", "core_unavailable")
        );
    }

    /// 还没初始化完：是「正在连」，不是「已连接」。
    #[test]
    fn an_unresumed_session_is_not_connected() {
        assert_eq!(
            derive_view(true, true, CoreState::Ready, false, false),
            ("connecting", "session_not_resumed")
        );
    }

    /// 没有设备在线只是在等，不是连上了。
    #[test]
    fn waiting_for_a_device_is_not_connected() {
        assert_eq!(
            derive_view(true, false, CoreState::Unknown, false, false),
            ("waiting", "no_device")
        );
    }

    /// 传输进程起不来时要说清是启动失败，而不是「没开」。
    #[test]
    fn a_failed_start_reports_its_own_reason() {
        assert_eq!(
            derive_view(false, false, CoreState::Unknown, false, true),
            ("offline", "start_failed")
        );
        assert_eq!(
            derive_view(false, false, CoreState::Unknown, false, false),
            ("offline", "offline")
        );
    }
}

/// 应用启动后自动拉起传输进程（正式版才做）。
///
/// user:“发布版本启动后 P2P 服务能真的起来：给出启动状况的可见状态”+(以前只有打开
/// 「设备连接」页才会起进程，没打开过就等于远程功能不存在。正式版启动即尝试，失败原因
/// 进状态，设备页直接显示)。
///
/// 开发版不自动起：dev 实例和已安装的正式版共用 `%APPDATA%/Sunday/p2p`，两个传输进程
/// 抢同一个身份与名单没有意义，开发时按需点「生成配对二维码」即可。
pub fn autostart(api_base: String, state: P2pHostState) {
    core_ready(&state, &api_base);
    // user:“Sunday 启动且 Core 就绪后自动恢复传输服务（确认它依赖开关与 Core 就绪，
    // 而不是无条件起）”+(开关关着就不起；开发版默认不自动起，避免和正式版抢同一个身份)。
    let forced = std::env::var("SUNDAY_P2P_AUTOSTART").as_deref() == Ok("1");
    if !read_prefs().auto_connect && !forced {
        eprintln!("[sunday] p2p autostart skipped: remote access is off");
        return;
    }
    if cfg!(debug_assertions) && !forced {
        return;
    }
    std::thread::spawn(move || {
        let port = url::Url::parse(api_base.trim())
            .ok()
            .and_then(|parsed| parsed.port())
            .unwrap_or(0);
        // Core 就绪再起：后端刚拉起时端口可能还没监听，急着起会拿到一个「连不上 Core」的
        // 传输进程，而且它的错误看起来像网络问题。
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(60);
        while std::time::Instant::now() < deadline {
            if probe_core(port) == CoreState::Ready {
                break;
            }
            std::thread::sleep(std::time::Duration::from_secs(1));
        }
        if probe_core(port) != CoreState::Ready {
            if let Ok(mut slot) = state.error.lock() {
                *slot = Some("Core 没有就绪，远程访问未能自动开启".to_owned());
            }
            eprintln!("[sunday] p2p autostart skipped: core is not ready");
            return;
        }
        match ensure_child(&api_base, &state, false) {
            Ok(_) => eprintln!("[sunday] p2p transport started on launch"),
            Err(error) => eprintln!("[sunday] p2p transport failed to start: {error}"),
        }
    });
}

/// 读/写「远程访问」开关。
#[tauri::command]
pub fn p2p_config_get() -> Result<Value, String> {
    Ok(json!({ "autoConnect": read_prefs().auto_connect }))
}

#[tauri::command]
pub fn p2p_config_set(auto_connect: bool) -> Result<Value, String> {
    let mut prefs = read_prefs();
    prefs.auto_connect = auto_connect;
    write_prefs(&prefs)?;
    Ok(json!({ "autoConnect": prefs.auto_connect }))
}

/// 从 `p2p-pairing.json` 里取出待确认设备。
///
/// 宿主不链接 `sunday-p2p`（iroh 的 windows 依赖会撞车），但两边读写的是同一份文件；
/// 这里只解释 `pending` 这一层，不猜别的字段。
fn pending_from_json(text: &str) -> Vec<Value> {
    let Ok(parsed) = serde_json::from_str::<Value>(text) else {
        return Vec::new();
    };
    let Some(map) = parsed.get("pending").and_then(|value| value.as_object()) else {
        return Vec::new();
    };
    let mut pending: Vec<Value> = map
        .values()
        .filter_map(|item| {
            let id = item.get("id")?.as_str()?;
            Some(json!({
                "id": id,
                "name": item.get("name").and_then(|value| value.as_str()).unwrap_or(""),
                "requestedAt": item.get("requested_at").and_then(|value| value.as_u64()).unwrap_or(0),
                "expiresAt": item.get("expires_at").and_then(|value| value.as_u64()).unwrap_or(0),
            }))
        })
        .collect();
    pending.sort_by_key(|item| item.get("requestedAt").and_then(|value| value.as_u64()).unwrap_or(0));
    pending
}

fn pending_devices() -> Vec<Value> {
    let path = data_dir().join("p2p-pairing.json");
    match std::fs::read_to_string(&path) {
        Ok(text) => pending_from_json(&text),
        Err(_) => Vec::new(),
    }
}

/// 确认 / 拒绝都由传输程序改文件：它同时握着可信名单和一次性票，宿主不另写一套。
fn run_pairing_command(action: &str, id: &str) -> Result<Value, String> {
    let id = id.trim();
    if id.is_empty() {
        return Err("缺少设备 id".to_owned());
    }
    let mut command = Command::new(binary()?);
    command
        .arg(action)
        .arg("--dir")
        .arg(data_dir())
        .arg("--id")
        .arg(id)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }
    let output = command
        .output()
        .map_err(|error| format!("无法执行配对确认：{error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    audit(action, json!({ "id": id, "output": text }));
    Ok(json!({ "ok": true, "output": text, "pending": pending_devices() }))
}

/// 待确认设备列表。
#[tauri::command]
pub fn p2p_pending() -> Result<Value, String> {
    Ok(json!({ "pending": pending_devices() }))
}

/// 电脑确认一台待确认设备：写可信名单并消费这张票。
#[tauri::command]
pub fn p2p_confirm_device(id: String) -> Result<Value, String> {
    run_pairing_command("confirm", &id)
}

/// 电脑拒绝一台待确认设备：票作废，设备进入撤销名单。
#[tauri::command]
pub fn p2p_reject_device(id: String) -> Result<Value, String> {
    run_pairing_command("reject", &id)
}

/// user:“允许撤销授权”+(传输进程把名单放在自己的目录里，这里改同一份文件)。
///
/// 传输进程每次握手前都会重读这份名单，所以撤销立即生效，不需要重启进程。
#[tauri::command]
pub fn p2p_devices() -> Result<Value, String> {
    let path = data_dir().join("p2p-trust.json");
    if !path.exists() {
        return Ok(json!({ "devices": [], "revoked": [] }));
    }
    let text = std::fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let parsed: Value = serde_json::from_str(&text).map_err(|error| error.to_string())?;
    Ok(json!({
        "devices": parsed.get("devices").cloned().unwrap_or_else(|| json!([])),
        "revoked": parsed.get("revoked").cloned().unwrap_or_else(|| json!([])),
    }))
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
    let name = list
        .iter()
        .find(|device| device.get("id").and_then(|value| value.as_str()) == Some(id.as_str()))
        .and_then(|device| device.get("name"))
        .and_then(|value| value.as_str())
        .unwrap_or("")
        .to_owned();
    let before = list.len();
    list.retain(|device| device.get("id").and_then(|value| value.as_str()) != Some(id.as_str()));
    let removed = list.len() != before;
    // user:“允许撤销授权”+(删除名单只是“忘了它”，首次连接还会自动信任；必须留一条撤销记录，
    // 传输进程在自动信任之前先查这张表)。
    if !parsed.get("revoked").map(|value| value.is_array()).unwrap_or(false) {
        parsed["revoked"] = json!([]);
    }
    if let Some(revoked) = parsed.get_mut("revoked").and_then(|value| value.as_array_mut()) {
        if !revoked
            .iter()
            .any(|device| device.get("id").and_then(|value| value.as_str()) == Some(id.as_str()))
        {
            let now = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|elapsed| elapsed.as_secs())
                .unwrap_or(0);
            revoked.push(json!({ "id": id, "name": name, "revoked_at": now }));
        }
    }
    std::fs::write(&path, serde_json::to_string_pretty(&parsed).map_err(|error| error.to_string())?)
        .map_err(|error| error.to_string())?;
    audit("revoke", json!({ "id": id, "removed": removed }));
    Ok(json!({ "removed": removed }))
}

/// 重新允许一台被撤销的设备：删掉撤销记录，下一次连接按首次配对处理。
#[tauri::command]
pub fn p2p_allow(id: String) -> Result<Value, String> {
    let path = data_dir().join("p2p-trust.json");
    if !path.exists() {
        return Ok(json!({ "allowed": false }));
    }
    let text = std::fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let mut parsed: Value = serde_json::from_str(&text).map_err(|error| error.to_string())?;
    let Some(revoked) = parsed.get_mut("revoked").and_then(|value| value.as_array_mut()) else {
        return Ok(json!({ "allowed": false }));
    };
    let before = revoked.len();
    revoked.retain(|device| device.get("id").and_then(|value| value.as_str()) != Some(id.as_str()));
    let allowed = revoked.len() != before;
    if allowed {
        std::fs::write(&path, serde_json::to_string_pretty(&parsed).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())?;
    }
    audit("allow", json!({ "id": id, "allowed": allowed }));
    Ok(json!({ "allowed": allowed }))
}

#[cfg(test)]
mod transport_startup_tests {
    use super::*;
    use std::io::Cursor;
    use std::sync::mpsc;
    use std::time::{Duration, Instant};

    #[test]
    fn relay_stability_forwards_the_actual_startup_error() {
        let error = sunday_p2p_status::StatusEvent::StartupFailed { message: "自定义中继地址无效".into() };
        let mut stdout = Cursor::new(error.render());
        assert_eq!(read_transport_startup(&mut stdout).err().as_deref(), Some("自定义中继地址无效"));
    }

    // user:“修完之后，去找远程连接/跨网通信/跨设备使用中最不稳定/问题最大的地方 修掉，并列出候选”+
    // (传输进程不输出时，桌面仍在规定时间内报告失败)。
    #[test]
    fn transport_startup_times_out_even_with_an_open_pipe() {
        let (_send, receive) = mpsc::channel::<Result<(), String>>();
        let started = Instant::now();
        let result = wait_for_transport_startup(receive, &AtomicBool::new(false), Duration::from_millis(30));
        assert!(result.unwrap_err().contains("超时"));
        assert!(started.elapsed() < Duration::from_secs(2));
    }

    #[test]
    fn transport_startup_does_not_treat_a_ticket_as_ready() {
        let mut reader = Cursor::new(b"TICKET sample\nEXPIRES 123\n");
        let result = read_transport_startup(&mut reader);
        assert!(result.err().unwrap().contains("就绪"));
    }

    #[test]
    fn transport_startup_waits_for_ready_and_keeps_following_output() {
        let mut reader = Cursor::new(b"TICKET sample\nEXPIRES 123\nREADY\nPEER phone\n");
        let code = read_transport_startup(&mut reader).unwrap();
        assert_eq!(code.ticket, "sample");
        assert_eq!(code.expires_at, 123);
        let mut next_line = String::new();
        reader.read_line(&mut next_line).unwrap();
        assert_eq!(next_line, "PEER phone\n");
    }

    #[test]
    fn transport_startup_honors_manual_stop() {
        let (_send, receive) = mpsc::channel::<Result<(), String>>();
        let result = wait_for_transport_startup(receive, &AtomicBool::new(true), Duration::from_secs(30));
        assert!(result.unwrap_err().contains("已停止"));
    }
}

#[cfg(test)]
mod pending_tests {
    use super::*;

    /// user:“电脑显示待确认设备，用户确认配对”+(宿主读传输进程写的同一份文件)。
    #[test]
    fn reads_pending_pairings_from_the_transport_file() {
        let text = r#"{"used":{},"pending":{"abc":{"id":"phone-1","name":"Phone","requested_at":10,"expires_at":300}}}"#;
        let pending = pending_from_json(text);
        assert_eq!(pending.len(), 1);
        assert_eq!(pending[0]["id"], "phone-1");
        assert_eq!(pending[0]["name"], "Phone");
        assert_eq!(pending[0]["expiresAt"], 300);
    }

    #[test]
    fn a_broken_pairing_file_never_looks_like_a_pending_device() {
        assert!(pending_from_json("not json").is_empty());
        assert!(pending_from_json("{}").is_empty());
    }
}

#[cfg(test)]
mod audit_tests {
    use super::*;

    #[test]
    fn audit_records_are_stable_json_lines() {
        let record = audit_record("revoke", json!({ "id": "phone-1" }), 42);
        assert_eq!(record["at"], 42);
        assert_eq!(record["event"], "revoke");
        assert_eq!(record["fields"]["id"], "phone-1");
    }
}
