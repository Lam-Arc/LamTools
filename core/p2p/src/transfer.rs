//! 设备间文件互传（最小闭环）。
//!
//! user:“设备文件互传（先做最小闭环）：发送方选择已信任设备 → 走 p2p 传过去；大文件分块、
//! 可取消、有进度；接收方落盘到约定目录、重名不覆盖；只允许已信任设备互传”+(这一层只做
//! 「一个文件从 A 到 B，看得见进度，失败说得清原因」)。
//!
//! 协议不动帧：`call` / `reply` / `error` / `event` 四类帧原样用，互传只是**新增 method**：
//!
//! ```text
//! call  file/offer    {id,name,size,chunk}          → {id,name,size,chunk,received}
//! call  file/chunk    {id,seq,data(base64)}         → {id,received,next}
//! call  file/complete {id}                          → {id,name,path,size}
//! call  file/cancel   {id,reason}                   → {id,cancelled}
//! event file/progress <Progress>                     （发送方与接收方都发）
//! ```
//!
//! 为什么用 call 分块而不是新开一条 QUIC 流：新流要改 `ServerLink::serve` 的读循环，
//! 而现有的 `call` 已经带按 `id` 配对、断链时把所有在途调用一次性置失败、每条调用前复核
//! 撤权这三件事。分块走它，等于免费得到「断线不挂死、撤权当场生效」。
//!
//! 已知取舍（写进汇报的下一步，不在本批做）：断点续传的跨重启恢复、目录打包、多文件并行。
//! 本版一次只承载一个文件的写入进度；分块是顺序的（`seq` 必须连着来），乱序直接拒绝，
//! 免得留下一个「半个文件」的静默损坏。

use std::collections::HashMap;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::anyhow;
use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

/// 互传用到的四个方法名（新增 method，不改帧格式）。
pub const METHOD_OFFER: &str = "file/offer";
pub const METHOD_CHUNK: &str = "file/chunk";
pub const METHOD_COMPLETE: &str = "file/complete";
pub const METHOD_CANCEL: &str = "file/cancel";

/// 进度事件的 method（走既有的 `event` 帧）。
pub const PROGRESS_EVENT: &str = "file/progress";

/// 这一个 method 是不是互传的（宿主/传输进程据此分流，其余原样转给 Core）。
pub fn is_transfer_method(method: &str) -> bool {
    matches!(
        method,
        METHOD_OFFER | METHOD_CHUNK | METHOD_COMPLETE | METHOD_CANCEL
    )
}

/// 一块的大小。256 KiB 在「一帧 JSON + base64」下仍然远小于 `MAX_FRAME_BYTES`，
/// 同时把 1 GB 文件的往返次数压到 4096 次以内。
pub const CHUNK_BYTES: usize = 256 * 1024;

/// 单个文件上限。留着不用是因为它顺便是一道「对端说它有 4 PB」的防线。
pub const MAX_FILE_BYTES: u64 = 8 * 1024 * 1024 * 1024;

/// 一个传输多久没有新块就作废（半个文件不该永远占着名字与临时文件）。
const IDLE: Duration = Duration::from_secs(180);

/// 文件名最长多少字符（按字符算，避免把中文截成半个字节）。
const MAX_NAME_CHARS: usize = 120;

/// 一个传输最多同时存在几个（防止对端不停 offer 把盘占满）。
const MAX_ACTIVE: usize = 8;

// ---- 错误码 -------------------------------------------------------------
//
// user:“未配对/已撤权一律拒绝并给错误码”“失败有明确原因（对端离线/被拒/磁盘满/超时）”+
// (错误码是给界面和脚本判断用的稳定标识；中文原因给人看。两样都要有，缺一个就会退化成
// 「传失败了」四个字)。

/// 这台设备不在可信名单里（握手已通过，但传输前复核发现已撤权）。
pub const CODE_UNTRUSTED: &str = "file_untrusted";
/// 文件名不合法：空、`..`、Windows 保留名、全是非法字符。
pub const CODE_BAD_NAME: &str = "file_bad_name";
/// 参数缺失 / 块序号不对 / 块太大。
pub const CODE_BAD_REQUEST: &str = "file_bad_request";
/// 超过单文件上限。
pub const CODE_TOO_LARGE: &str = "file_too_large";
/// 这个传输 id 不在进行中（过期、取消过，或根本没 offer）。
pub const CODE_NOT_FOUND: &str = "file_not_found";
/// 同时在传的文件太多。
pub const CODE_BUSY: &str = "file_busy";
/// 写盘失败（磁盘满、目录不可写、重命名失败）。
pub const CODE_DISK: &str = "file_disk_error";
/// 收到的字节数与 offer 声明的不一致。
pub const CODE_SIZE_MISMATCH: &str = "file_size_mismatch";
/// 太久没有新块。
pub const CODE_TIMEOUT: &str = "file_timeout";
/// 对端取消，或本端主动取消。
pub const CODE_CANCELLED: &str = "file_cancelled";
/// 对端拒了这一次调用（消息里带着对端的错误码与原因）。
pub const CODE_PEER: &str = "file_peer_error";

/// 一个可判定的传输错误：稳定码 + 给人看的原因。
#[derive(Debug, Clone)]
pub struct TransferError {
    code: &'static str,
    message: String,
}

impl TransferError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    /// 稳定码（界面按它分支，不匹配中文）。
    pub fn code(&self) -> &'static str {
        self.code
    }

    /// 给人看的原因。
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl std::fmt::Display for TransferError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "[{}] {}", self.code, self.message)
    }
}

impl std::error::Error for TransferError {}

/// 传输进度。
///
/// user:“发送与接收都要有可观察进度（百分比或已传字节）”+(`percent` 是给进度条用的，
/// `transferred`/`total` 是给「12 MB / 240 MB」这种文案用的；`state` 是稳定词，界面不
/// 需要解析中文)。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Progress {
    /// 同一次传输两端用同一个 id（发送方生成）。
    pub transfer_id: String,
    /// `send` / `receive`：这一行是本端视角的方向。
    pub direction: String,
    pub name: String,
    pub total: u64,
    pub transferred: u64,
    pub percent: u8,
    /// `offered` / `transferring` / `completed` / `failed` / `cancelled`。
    pub state: String,
    /// 失败/取消时的稳定码；正常流程为空串。
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub code: String,
    /// 给人看的一句话（失败原因）。
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub message: String,
    /// 接收端落盘路径（完成时才有）。
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub path: String,
}

impl Progress {
    fn at(
        transfer_id: &str,
        direction: &str,
        name: &str,
        total: u64,
        transferred: u64,
        state: &str,
    ) -> Self {
        Self {
            transfer_id: transfer_id.to_owned(),
            direction: direction.to_owned(),
            name: name.to_owned(),
            total,
            transferred,
            percent: percent_of(transferred, total, state == "completed"),
            state: state.to_owned(),
            code: String::new(),
            message: String::new(),
            path: String::new(),
        }
    }

    fn failed(mut self, code: &str, message: &str) -> Self {
        self.state = "failed".to_owned();
        self.code = code.to_owned();
        self.message = message.to_owned();
        self
    }
}

/// 百分比：总数还没定下来（0 字节文件）时，只有完成才算 100%。
fn percent_of(transferred: u64, total: u64, completed: bool) -> u8 {
    if total == 0 {
        return if completed { 100 } else { 0 };
    }
    let percent = transferred.saturating_mul(100) / total;
    percent.min(100) as u8
}

/// 进度回调。传输层不认识 UI、不认识进程：它只把一条 `Progress` 交出去。
pub type ProgressSink = Arc<dyn Fn(Progress) + Send + Sync>;

/// 给不需要进度的调用方（测试、离线脚本）用。
pub fn null_sink() -> ProgressSink {
    Arc::new(|_| {})
}

fn emit(sink: &ProgressSink, progress: Progress) {
    // 回调是调用方给的：它 panic 不能把一次传输带崩（协议层不该替 UI 承担崩溃）。
    let guard = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| sink(progress)));
    if guard.is_err() {
        println!("[sunday-p2p] a progress sink panicked; the transfer continues");
    }
}

fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs() as i64)
        .unwrap_or(0)
}

fn new_transfer_id() -> String {
    static COUNTER: AtomicU64 = AtomicU64::new(1);
    format!(
        "{:x}-{:x}",
        now_secs(),
        COUNTER.fetch_add(1, Ordering::SeqCst)
    )
}

// ---- 文件名净化 ---------------------------------------------------------

/// 把对端给的名字变成「一个能安全落在接收目录里的文件名」。
///
/// user:“文件名净化（防路径穿越）”“重名不覆盖”+(对方可能是手机、也可能是被劫持的对端；
/// 名字里出现 `..`、绝对路径、盘符、Windows 保留设备名，都必须在写盘之前就被掐掉，
/// 而不是落在 `received/` 之外)。
pub fn sanitize_file_name(raw: &str) -> Result<String, TransferError> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(TransferError::new(CODE_BAD_NAME, "文件名是空的"));
    }
    // 只保留最后一段：`../../etc/passwd`、`C:\Windows\system32\x.txt` 都退化成文件名本身。
    // 这里不做「拒绝」而做「取最后一段」，是因为手机上选文件时常常带上完整路径。
    let last = trimmed.rsplit(['/', '\\']).next().unwrap_or("");
    let mut cleaned = String::with_capacity(last.len());
    for character in last.chars() {
        // 控制字符会在某些文件系统上截断名字；`<>:"|?*` 在 Windows 上非法。
        let forbidden = character.is_control() || matches!(character, '<' | '>' | ':' | '"' | '|' | '?' | '*');
        if !forbidden {
            cleaned.push(character);
        }
    }
    // Windows 会悄悄丢掉结尾的点与空格，导致「记录里的名字」和「盘上的名字」不一致。
    let cleaned = cleaned.trim_end_matches([' ', '.']).trim().to_owned();
    if cleaned.is_empty() || cleaned == "." || cleaned == ".." {
        return Err(TransferError::new(CODE_BAD_NAME, "文件名是空的"));
    }
    if is_reserved_device_name(&cleaned) {
        return Err(TransferError::new(
            CODE_BAD_NAME,
            format!("{cleaned} 是 Windows 的保留设备名，不能当文件名"),
        ));
    }
    Ok(clamp_name(&cleaned))
}

/// `CON`、`NUL`、`COM1`… 在任何目录下都不该被当成普通文件创建。
fn is_reserved_device_name(name: &str) -> bool {
    let stem = name.split('.').next().unwrap_or(name).to_ascii_uppercase();
    if matches!(stem.as_str(), "CON" | "PRN" | "AUX" | "NUL") {
        return true;
    }
    let mut chars = stem.chars();
    let Some(prefix) = chars.next() else {
        return false;
    };
    let rest: String = chars.collect();
    if matches!(prefix, 'C' | 'L') && rest.len() == 3 {
        let digits = if prefix == 'C' { "OM" } else { "PT" };
        if rest.starts_with(digits) && rest[2..].chars().all(|c| c.is_ascii_digit()) {
            return true;
        }
    }
    false
}

/// 名字太长就截断，但保留扩展名（截断后看不出类型比长一点更糟）。
fn clamp_name(name: &str) -> String {
    if name.chars().count() <= MAX_NAME_CHARS {
        return name.to_owned();
    }
    let (stem, ext) = match name.rsplit_once('.') {
        Some((stem, ext)) if !stem.is_empty() && ext.len() <= 12 => (stem, Some(ext)),
        _ => (name, None),
    };
    let keep = MAX_NAME_CHARS.saturating_sub(ext.map(|ext| ext.chars().count() + 1).unwrap_or(0));
    let stem: String = stem.chars().take(keep).collect();
    match ext {
        Some(ext) => format!("{stem}.{ext}"),
        None => stem,
    }
}

// ---- 接收目录与重名 -----------------------------------------------------

/// `<root>/<YYYY-MM-DD>`：按日分目录，文件夹不会因为长期使用变成几千个文件一堆。
pub fn day_dir_for(root: &Path, unix_secs: i64) -> PathBuf {
    root.join(civil_date(unix_secs))
}

/// 公历日期（UTC）。不引 chrono：只要一个 yyyy-mm-dd。
pub fn civil_date(unix_secs: i64) -> String {
    let days = unix_secs.div_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    format!("{year:04}-{month:02}-{day:02}")
}

/// Howard Hinnant 的 `civil_from_days`：1970-01-01 起的天数 → 年月日。
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365; // [0, 399]
    let year = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let day = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let month = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if month <= 2 { year + 1 } else { year }, month, day)
}

/// 在 `dir` 里抢一个「还不存在」的名字，返回占好位的文件与它的路径。
///
/// `create_new` 是原子的：两个同名传输同时完成时，只会有一个拿到 `a.txt`，另一个自动
/// 落到 `a (2).txt`。这就是「重名不覆盖」的实现方式，不靠先 `exists()` 再创建。
fn reserve_name(dir: &Path, name: &str) -> Result<(File, PathBuf), TransferError> {
    for index in 1..=999u32 {
        let candidate = if index == 1 {
            name.to_owned()
        } else {
            numbered_name(name, index)
        };
        let path = dir.join(&candidate);
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(file) => return Ok((file, path)),
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(TransferError::new(
                    CODE_DISK,
                    format!("无法在接收目录创建文件：{error}"),
                ))
            }
        }
    }
    Err(TransferError::new(
        CODE_BUSY,
        format!("同名文件已经堆了 999 份，请先清理 {name}"),
    ))
}

/// `a.txt` + 2 → `a (2).txt`
fn numbered_name(name: &str, index: u32) -> String {
    match name.rsplit_once('.') {
        Some((stem, ext)) if !stem.is_empty() => format!("{stem} ({index}).{ext}"),
        _ => format!("{name} ({index})"),
    }
}

/// transfer id 会进临时文件名：只留字母数字与 `-`/`_`，别的一律丢掉。
fn safe_id(id: &str) -> String {
    let cleaned: String = id
        .chars()
        .filter(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_'))
        .take(64)
        .collect();
    if cleaned.is_empty() {
        "transfer".to_owned()
    } else {
        cleaned
    }
}

// ---- 接收端 -------------------------------------------------------------

struct Incoming {
    name: String,
    /// 已经占好位的最终路径（0 字节）。
    target: PathBuf,
    /// 数据先写到这个 `.part`，完成时才顶上最终名字。
    part: PathBuf,
    file: Option<File>,
    size: u64,
    received: u64,
    next_seq: u64,
    last: Instant,
    last_percent: u8,
}

struct Inner {
    active: HashMap<String, Incoming>,
}

/// 接收端：把 `file/*` 方法落到 `<root>/<日期>/` 下的一个真实文件。
///
/// `trusted` 来自握手结论，并在每次调用前复核（`gate::authorize`）。握手通过但随后被撤权
/// 的设备，会在这里拿到 `file_untrusted`，而不是把文件写进用户目录。
pub struct Receiver {
    root: PathBuf,
    trusted: bool,
    sink: ProgressSink,
    inner: Mutex<Inner>,
}

impl Receiver {
    pub fn new(root: impl Into<PathBuf>, trusted: bool, sink: ProgressSink) -> Self {
        Self {
            root: root.into(),
            trusted,
            sink,
            inner: Mutex::new(Inner {
                active: HashMap::new(),
            }),
        }
    }

    /// 接收目录（宿主展示「传到哪」、UI 给「所在文件夹」入口都用它）。
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// 处理一条 `file/*` 调用。
    pub fn handle(&self, method: &str, params: &Value) -> Result<Value, TransferError> {
        self.sweep_stale();
        if !self.trusted {
            return Err(TransferError::new(
                CODE_UNTRUSTED,
                "这台设备没有互传权限（未配对或已被移除授权）",
            ));
        }
        match method {
            METHOD_OFFER => self.offer(params),
            METHOD_CHUNK => self.chunk(params),
            METHOD_COMPLETE => self.complete(params),
            METHOD_CANCEL => self.cancel(params),
            other => Err(TransferError::new(
                CODE_BAD_REQUEST,
                format!("不认识的文件方法 {other}"),
            )),
        }
    }

    fn offer(&self, params: &Value) -> Result<Value, TransferError> {
        let id = text(params, "id")?;
        let mut name = sanitize_file_name(&text(params, "name")?)?;
        let size = number(params, "size")?;
        if size > MAX_FILE_BYTES {
            return Err(TransferError::new(
                CODE_TOO_LARGE,
                format!("文件超过上限 {} 字节", MAX_FILE_BYTES),
            ));
        }
        let day = day_dir_for(&self.root, now_secs());
        fs::create_dir_all(&day).map_err(|error| {
            TransferError::new(CODE_DISK, format!("无法创建接收目录 {}：{error}", day.display()))
        })?;
        let mut inner = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if inner.active.contains_key(&id) {
            return Err(TransferError::new(
                CODE_BUSY,
                format!("传输 {id} 已经在进行中"),
            ));
        }
        if inner.active.len() >= MAX_ACTIVE {
            return Err(TransferError::new(
                CODE_BUSY,
                format!("同时进行的传输太多了（上限 {MAX_ACTIVE}），请稍后再试"),
            ));
        }
        let (placeholder, target) = reserve_name(&day, &name)?;
        drop(placeholder);
        // user:“重名不覆盖”+(撞上已有文件时落盘名是 `a (2).txt`：把这个真实名字回去，
        // 两端的进度、资料库条目、用户看到的才是同一个名字，而不是各说各的)。
        if let Some(actual) = target.file_name().and_then(|item| item.to_str()) {
            name = actual.to_owned();
        }
        let part = day.join(format!(".{}.part", safe_id(&id)));
        let file = File::create(&part).map_err(|error| {
            TransferError::new(CODE_DISK, format!("无法创建临时文件：{error}"))
        })?;
        inner.active.insert(
            id.clone(),
            Incoming {
                name: name.clone(),
                target: target.clone(),
                part,
                file: Some(file),
                size,
                received: 0,
                next_seq: 0,
                last: Instant::now(),
                last_percent: 0,
            },
        );
        drop(inner);
        emit(
            &self.sink,
            Progress::at(&id, "receive", &name, size, 0, "offered"),
        );
        Ok(json!({
            "id": id,
            "name": name,
            "size": size,
            "chunk": CHUNK_BYTES,
            "received": 0u64,
        }))
    }

    fn chunk(&self, params: &Value) -> Result<Value, TransferError> {
        let id = text(params, "id")?;
        let seq = number(params, "seq")?;
        let encoded = text(params, "data")?;
        let bytes = B64
            .decode(encoded.as_bytes())
            .map_err(|error| TransferError::new(CODE_BAD_REQUEST, format!("块不是合法的 base64：{error}")))?;
        if bytes.is_empty() {
            return Err(TransferError::new(CODE_BAD_REQUEST, "收到一个空块"));
        }
        if bytes.len() > CHUNK_BYTES {
            return Err(TransferError::new(
                CODE_BAD_REQUEST,
                format!("块太大（{} > {CHUNK_BYTES}）", bytes.len()),
            ));
        }
        let mut inner = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(entry) = inner.active.get_mut(&id) else {
            return Err(TransferError::new(
                CODE_NOT_FOUND,
                format!("传输 {id} 不在进行中（可能已超时或已取消）"),
            ));
        };
        if seq != entry.next_seq {
            return Err(TransferError::new(
                CODE_BAD_REQUEST,
                format!("块序号不对：期望 {}，收到 {seq}", entry.next_seq),
            ));
        }
        if entry.received + bytes.len() as u64 > entry.size {
            return Err(TransferError::new(
                CODE_SIZE_MISMATCH,
                format!("收到的字节数会超过声明的 {} 字节", entry.size),
            ));
        }
        let write = entry
            .file
            .as_mut()
            .ok_or_else(|| TransferError::new(CODE_DISK, "临时文件已经关闭"))
            .and_then(|file| {
                file.write_all(&bytes)
                    .map_err(|error| TransferError::new(CODE_DISK, format!("写盘失败：{error}")))
            });
        if let Err(error) = write {
            let name = entry.name.clone();
            inner.active.remove(&id);
            drop(inner);
            emit(&self.sink, Progress::at(&id, "receive", &name, 0, 0, "failed").failed(error.code(), error.message()));
            return Err(error);
        }
        entry.received += bytes.len() as u64;
        entry.next_seq += 1;
        entry.last = Instant::now();
        let received = entry.received;
        let size = entry.size;
        let name = entry.name.clone();
        let percent = percent_of(received, size, false);
        let should_emit = percent != entry.last_percent || received == size;
        entry.last_percent = percent;
        drop(inner);
        if should_emit {
            emit(
                &self.sink,
                Progress::at(&id, "receive", &name, size, received, "transferring"),
            );
        }
        Ok(json!({ "id": id, "received": received, "next": seq + 1 }))
    }

    fn complete(&self, params: &Value) -> Result<Value, TransferError> {
        let id = text(params, "id")?;
        let mut inner = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(mut entry) = inner.active.remove(&id) else {
            return Err(TransferError::new(
                CODE_NOT_FOUND,
                format!("传输 {id} 不在进行中"),
            ));
        };
        if entry.received != entry.size {
            let message = format!(
                "收到的字节数 {} 与声明的 {} 不一致",
                entry.received, entry.size
            );
            drop(entry.file.take());
            let _ = fs::remove_file(&entry.part);
            let _ = fs::remove_file(&entry.target);
            drop(inner);
            emit(
                &self.sink,
                Progress::at(&id, "receive", &entry.name, entry.size, entry.received, "failed")
                    .failed(CODE_SIZE_MISMATCH, &message),
            );
            return Err(TransferError::new(CODE_SIZE_MISMATCH, message));
        }
        // Windows 上「覆盖已存在文件」的 rename 会失败：先关句柄、再放掉占位名。
        drop(entry.file.take());
        let _ = fs::remove_file(&entry.target);
        if let Err(error) = fs::rename(&entry.part, &entry.target) {
            let _ = fs::remove_file(&entry.part);
            drop(inner);
            let message = format!("落盘失败：{error}");
            emit(
                &self.sink,
                Progress::at(&id, "receive", &entry.name, entry.size, entry.received, "failed")
                    .failed(CODE_DISK, &message),
            );
            return Err(TransferError::new(CODE_DISK, message));
        }
        drop(inner);
        let path = entry.target.to_string_lossy().to_string();
        let mut progress = Progress::at(&id, "receive", &entry.name, entry.size, entry.size, "completed");
        progress.path = path.clone();
        emit(&self.sink, progress);
        Ok(json!({
            "id": id,
            "name": entry.name,
            "path": path,
            "size": entry.size,
        }))
    }

    fn cancel(&self, params: &Value) -> Result<Value, TransferError> {
        let id = text(params, "id")?;
        let reason = params
            .get("reason")
            .and_then(Value::as_str)
            .unwrap_or("对端取消了传输")
            .to_owned();
        let mut inner = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        let Some(mut entry) = inner.active.remove(&id) else {
            return Ok(json!({ "id": id, "cancelled": false }));
        };
        drop(entry.file.take());
        let _ = fs::remove_file(&entry.part);
        let _ = fs::remove_file(&entry.target);
        let size = entry.size;
        let received = entry.received;
        let name = entry.name.clone();
        drop(inner);
        let mut progress = Progress::at(&id, "receive", &name, size, received, "cancelled");
        progress.code = CODE_CANCELLED.to_owned();
        progress.message = reason;
        emit(&self.sink, progress);
        Ok(json!({ "id": id, "cancelled": true }))
    }

    /// 太久没动静的传输当场作废：不放着半个文件占名字。
    fn sweep_stale(&self) {
        let mut expired: Vec<Incoming> = Vec::new();
        {
            let mut inner = self.inner.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
            let stale: Vec<String> = inner
                .active
                .iter()
                .filter(|(_, entry)| entry.last.elapsed() > IDLE)
                .map(|(id, _)| id.clone())
                .collect();
            for id in stale {
                if let Some(entry) = inner.active.remove(&id) {
                    expired.push(entry);
                }
            }
        }
        for mut entry in expired {
            drop(entry.file.take());
            let _ = fs::remove_file(&entry.part);
            let _ = fs::remove_file(&entry.target);
            println!(
                "[sunday-p2p] transfer swept: {} ({})",
                entry.name,
                entry.target.display()
            );
        }
    }
}

// ---- 发送端 -------------------------------------------------------------

/// 一次成功发送的结果。
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SentFile {
    pub name: String,
    pub bytes: u64,
    pub chunks: u64,
    /// 对端落盘的绝对路径（对端没给就是空串）。
    pub remote_path: String,
}

/// 把本地一个文件发给对端。
///
/// `call` 就是这条隧道上的普通调用（`Client::call` 或宿主自己的转发函数）：互传不要求
/// 调用方知道帧长什么样。中途任何一步失败都会尽力发一条 `file/cancel`，不让对端留下
/// 半个文件与一个 `.part`。
pub async fn send_file<F, Fut>(
    mut call: F,
    path: &Path,
    as_name: Option<&str>,
    sink: &ProgressSink,
) -> Result<SentFile, TransferError>
where
    F: FnMut(String, Value) -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<Value>>,
{
    let fallback = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("file");
    let name = sanitize_file_name(as_name.unwrap_or(fallback))?;
    let metadata = fs::metadata(path).map_err(|error| {
        TransferError::new(CODE_BAD_REQUEST, format!("读不到 {}：{error}", path.display()))
    })?;
    if !metadata.is_file() {
        return Err(TransferError::new(
            CODE_BAD_REQUEST,
            format!("{} 不是一个文件", path.display()),
        ));
    }
    let size = metadata.len();
    if size > MAX_FILE_BYTES {
        return Err(TransferError::new(
            CODE_TOO_LARGE,
            format!("文件超过上限 {} 字节", MAX_FILE_BYTES),
        ));
    }
    let id = new_transfer_id();
    emit(
        sink,
        Progress::at(&id, "send", &name, size, 0, "offered"),
    );
    let offer = call(
        METHOD_OFFER.to_owned(),
        json!({ "id": id, "name": name, "size": size, "chunk": CHUNK_BYTES }),
    )
    .await
    .map_err(|error| TransferError::new(CODE_PEER, format!("{error:#}")))?;
    // 对端可能给了一个不重名的新名字（`a (2).txt`）：后面报的就是它。
    let accepted_name = offer
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or(&name)
        .to_owned();

    let mut file = File::open(path).map_err(|error| {
        TransferError::new(CODE_BAD_REQUEST, format!("打不开 {}：{error}", path.display()))
    })?;
    let mut buffer = vec![0u8; CHUNK_BYTES];
    let mut seq: u64 = 0;
    let mut sent: u64 = 0;
    let mut last_percent: u8 = 0;
    loop {
        let read = match file.read(&mut buffer) {
            Ok(0) => break,
            Ok(read) => read,
            Err(error) => {
                let _ = call(
                    METHOD_CANCEL.to_owned(),
                    json!({ "id": id, "reason": format!("读本地文件失败：{error}") }),
                )
                .await;
                let message = format!("读本地文件失败：{error}");
                emit(
                    sink,
                    Progress::at(&id, "send", &accepted_name, size, sent, "failed")
                        .failed(CODE_BAD_REQUEST, &message),
                );
                return Err(TransferError::new(CODE_BAD_REQUEST, message));
            }
        };
        if let Err(error) = call(
            METHOD_CHUNK.to_owned(),
            json!({ "id": id, "seq": seq, "data": B64.encode(&buffer[..read]) }),
        )
        .await
        {
            let _ = call(
                METHOD_CANCEL.to_owned(),
                json!({ "id": id, "reason": format!("{error:#}") }),
            )
            .await;
            let message = format!("{error:#}");
            emit(
                sink,
                Progress::at(&id, "send", &accepted_name, size, sent, "failed")
                    .failed(CODE_PEER, &message),
            );
            return Err(TransferError::new(CODE_PEER, message));
        }
        sent += read as u64;
        seq += 1;
        let percent = percent_of(sent, size, sent == size);
        // 每 1% 一条：400 条的进度条已经够顺，别让进度事件把隧道占满。
        if percent != last_percent || sent == size {
            last_percent = percent;
            emit(
                sink,
                Progress::at(&id, "send", &accepted_name, size, sent, "transferring"),
            );
        }
    }
    let done = call(METHOD_COMPLETE.to_owned(), json!({ "id": id }))
        .await
        .map_err(|error| TransferError::new(CODE_PEER, format!("{error:#}")))?;
    let remote_path = done
        .get("path")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_owned();
    let mut progress = Progress::at(&id, "send", &accepted_name, size, sent, "completed");
    progress.path = remote_path.clone();
    emit(sink, progress);
    Ok(SentFile {
        name: accepted_name,
        bytes: sent,
        chunks: seq,
        remote_path,
    })
}

fn text(params: &Value, key: &str) -> Result<String, TransferError> {
    params
        .get(key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| TransferError::new(CODE_BAD_REQUEST, format!("缺少参数 {key}")))
}

fn number(params: &Value, key: &str) -> Result<u64, TransferError> {
    params
        .get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| TransferError::new(CODE_BAD_REQUEST, format!("缺少参数 {key}（应为非负整数）")))
}

/// 一句给日志/界面看的失败描述（CLI 用它把 `TransferError` 变成 `anyhow`）。
pub fn as_anyhow(error: TransferError) -> anyhow::Error {
    anyhow!("{error}")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    fn temp_dir(tag: &str) -> PathBuf {
        static COUNTER: AtomicUsize = AtomicUsize::new(0);
        let dir = std::env::temp_dir().join(format!(
            "sunday-transfer-{tag}-{}-{}",
            std::process::id(),
            COUNTER.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir");
        dir
    }

    fn receiver(root: &Path, trusted: bool) -> (Receiver, Arc<Mutex<Vec<Progress>>>) {
        let seen = Arc::new(Mutex::new(Vec::new()));
        let sink_seen = Arc::clone(&seen);
        let sink: ProgressSink = Arc::new(move |progress| {
            sink_seen.lock().unwrap().push(progress);
        });
        (Receiver::new(root, trusted, sink), seen)
    }

    /// 把一段字节按 straight-forward 的方式切块，走一遍 offer/chunk/complete。
    fn deliver(receiver: &Receiver, name: &str, bytes: &[u8]) -> Result<Value, TransferError> {
        let id = "t1";
        receiver.handle(
            METHOD_OFFER,
            &json!({ "id": id, "name": name, "size": bytes.len() }),
        )?;
        for (seq, piece) in bytes.chunks(CHUNK_BYTES).enumerate() {
            receiver.handle(
                METHOD_CHUNK,
                &json!({ "id": id, "seq": seq, "data": B64.encode(piece) }),
            )?;
        }
        receiver.handle(METHOD_COMPLETE, &json!({ "id": id }))
    }

    /// user:“文件名净化（防路径穿越）”+(对端给什么名字都不能让文件落到接收目录之外)。
    #[test]
    fn file_names_never_escape_the_receive_directory() {
        assert_eq!(sanitize_file_name("../../etc/passwd").unwrap(), "passwd");
        assert_eq!(sanitize_file_name("/tmp/a.txt").unwrap(), "a.txt");
        assert_eq!(
            sanitize_file_name(r"C:\Windows\system32\x.txt").unwrap(),
            "x.txt"
        );
        assert_eq!(sanitize_file_name("..\\..\\evil.exe").unwrap(), "evil.exe");
        // 非法字符被去掉，但名字还在。
        assert_eq!(sanitize_file_name("a<b>c:d.txt").unwrap(), "abcd.txt");
        // 结尾的点与空格会被 Windows 悄悄吃掉。
        assert_eq!(sanitize_file_name("report. ").unwrap(), "report");
        // 控制字符被去掉。
        assert_eq!(sanitize_file_name("a\u{0}b.txt").unwrap(), "ab.txt");
    }

    /// 空名字、纯点、保留设备名：一律拒绝，而不是猜一个名字。
    #[test]
    fn reserved_and_empty_names_are_refused() {
        for raw in ["", "   ", ".", "..", "...", "CON", "nul.txt", "COM1", "LPT9.log"] {
            let error = sanitize_file_name(raw).expect_err(raw);
            assert_eq!(error.code(), CODE_BAD_NAME, "raw={raw}");
        }
        // 只是以 CON 开头但不是设备名的，照收。
        assert_eq!(sanitize_file_name("console.txt").unwrap(), "console.txt");
    }

    /// 太长的名字截断，但扩展名要留着。
    #[test]
    fn a_long_name_keeps_its_extension() {
        let long = format!("{}.txt", "a".repeat(300));
        let clamped = sanitize_file_name(&long).unwrap();
        assert!(clamped.chars().count() <= MAX_NAME_CHARS);
        assert!(clamped.ends_with(".txt"));
    }

    /// user:“分块边界”+(整块、跨块、最后一块不满，拼回来必须逐字节相等)。
    #[test]
    fn chunk_boundaries_reassemble_byte_for_byte() {
        let root = temp_dir("boundaries");
        let (receiver, seen) = receiver(&root, true);
        let size = CHUNK_BYTES * 2 + 777;
        let payload: Vec<u8> = (0..size).map(|index| (index % 251) as u8).collect();
        let done = deliver(&receiver, "big.bin", &payload).expect("delivered");
        let path = PathBuf::from(done["path"].as_str().unwrap());
        assert_eq!(fs::read(&path).unwrap(), payload);
        let seen = seen.lock().unwrap();
        let last = seen.last().expect("progress");
        assert_eq!(last.state, "completed");
        assert_eq!(last.transferred, size as u64);
        assert_eq!(last.percent, 100);
        assert_eq!(last.path, path.to_string_lossy());
    }

    /// 声明 10 字节却发了 20 字节：当场拒绝，不写进盘。
    #[test]
    fn a_chunk_may_not_cross_the_declared_size() {
        let root = temp_dir("oversize");
        let (receiver, _) = receiver(&root, true);
        receiver
            .handle(METHOD_OFFER, &json!({ "id": "t", "name": "a.bin", "size": 10 }))
            .unwrap();
        let error = receiver
            .handle(
                METHOD_CHUNK,
                &json!({ "id": "t", "seq": 0, "data": B64.encode(vec![0u8; 20]) }),
            )
            .expect_err("must refuse");
        assert_eq!(error.code(), CODE_SIZE_MISMATCH);
    }

    /// 乱序块与未知 id 都要明确报错：静默接受会写出一个坏文件。
    #[test]
    fn chunks_must_arrive_in_order_and_an_unknown_id_is_refused() {
        let root = temp_dir("order");
        let (receiver, _) = receiver(&root, true);
        receiver
            .handle(METHOD_OFFER, &json!({ "id": "t", "name": "a.bin", "size": 4 }))
            .unwrap();
        let error = receiver
            .handle(
                METHOD_CHUNK,
                &json!({ "id": "t", "seq": 3, "data": B64.encode([1u8, 2]) }),
            )
            .expect_err("out of order");
        assert_eq!(error.code(), CODE_BAD_REQUEST);

        let error = receiver
            .handle(
                METHOD_CHUNK,
                &json!({ "id": "nope", "seq": 0, "data": B64.encode([1u8]) }),
            )
            .expect_err("unknown id");
        assert_eq!(error.code(), CODE_NOT_FOUND);
    }

    /// user:“重名不覆盖”+(同名文件落成 `a (2).txt`，原来那份一个字节都不动)。
    #[test]
    fn a_second_file_with_the_same_name_does_not_overwrite_the_first() {
        let root = temp_dir("duplicate");
        let (receiver, _) = receiver(&root, true);
        let first = deliver(&receiver, "note.txt", b"first").expect("first");
        let second = deliver(&receiver, "note.txt", b"second").expect("second");
        assert_ne!(first["path"], second["path"]);
        assert_eq!(fs::read(first["path"].as_str().unwrap()).unwrap(), b"first");
        assert_eq!(
            fs::read(second["path"].as_str().unwrap()).unwrap(),
            b"second"
        );
        assert!(second["name"].as_str().unwrap().contains("(2)"));
    }

    /// user:“未配对/已撤权一律拒绝并给错误码”+(拒绝发生在写盘之前：目录里什么都不该多)。
    #[test]
    fn an_untrusted_peer_is_refused_before_anything_is_written() {
        let root = temp_dir("untrusted");
        let (receiver, seen) = receiver(&root, false);
        let error = receiver
            .handle(METHOD_OFFER, &json!({ "id": "t", "name": "a.txt", "size": 3 }))
            .expect_err("revoked device must be refused");
        assert_eq!(error.code(), CODE_UNTRUSTED);
        assert!(fs::read_dir(&root).unwrap().next().is_none(), "不能留下任何文件");
        assert!(seen.lock().unwrap().is_empty(), "拒绝不需要进度");
    }

    /// user:“进度事件形状”+(宿主与界面按这些字段读；多一个少一个都要在这里被抓住)。
    #[test]
    fn the_progress_event_has_the_shape_the_host_reads() {
        let mut progress = Progress::at("t-1", "receive", "a.txt", 200, 50, "transferring");
        progress.path = "/tmp/a.txt".to_owned();
        let value = serde_json::to_value(&progress).unwrap();
        assert_eq!(value["transfer_id"], "t-1");
        assert_eq!(value["direction"], "receive");
        assert_eq!(value["name"], "a.txt");
        assert_eq!(value["total"], 200);
        assert_eq!(value["transferred"], 50);
        assert_eq!(value["percent"], 25);
        assert_eq!(value["state"], "transferring");
        assert_eq!(value["path"], "/tmp/a.txt");
        // 空字段不出现：界面不会被一堆空串覆盖掉上一次的真实值。
        assert!(value.get("code").is_none());
        assert!(value.get("message").is_none());

        // 0 字节文件：没完成是 0%，完成才是 100%。
        assert_eq!(percent_of(0, 0, false), 0);
        assert_eq!(percent_of(0, 0, true), 100);
        // 永远不会超过 100（对端谎报 total 也不会画出 120%）。
        assert_eq!(percent_of(500, 100, false), 100);
    }

    /// 日期目录是 UTC 的 `yyyy-mm-dd`：换机器、换时区不该把文件放进不同的日子。
    #[test]
    fn the_date_folder_is_utc_yyyy_mm_dd() {
        assert_eq!(civil_date(0), "1970-01-01");
        assert_eq!(civil_date(1_700_000_000), "2023-11-14");
        assert_eq!(
            day_dir_for(Path::new("C:/recv"), 1_700_000_000),
            Path::new("C:/recv/2023-11-14")
        );
    }

    /// 取消要清干净：不留下 `.part`，也不留下占位文件。
    #[test]
    fn cancelling_leaves_no_debris() {
        let root = temp_dir("cancel");
        let (receiver, _) = receiver(&root, true);
        receiver
            .handle(METHOD_OFFER, &json!({ "id": "t", "name": "half.bin", "size": 10 }))
            .unwrap();
        receiver
            .handle(
                METHOD_CHUNK,
                &json!({ "id": "t", "seq": 0, "data": B64.encode([1u8, 2, 3]) }),
            )
            .unwrap();
        let answer = receiver
            .handle(METHOD_CANCEL, &json!({ "id": "t", "reason": "用户取消" }))
            .unwrap();
        assert_eq!(answer["cancelled"], true);
        let day = day_dir_for(&root, now_secs());
        let leftovers: Vec<String> = fs::read_dir(&day)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().to_string())
            .collect();
        assert!(leftovers.is_empty(), "取消后还剩：{leftovers:?}");
    }

    /// 只有互传的四个方法被分流，别的方法不能被我方截走。
    #[test]
    fn only_the_four_transfer_methods_are_claimed() {
        for method in [METHOD_OFFER, METHOD_CHUNK, METHOD_COMPLETE, METHOD_CANCEL] {
            assert!(is_transfer_method(method));
        }
        for method in ["file/other", "file", "thread/resume", "core_http"] {
            assert!(!is_transfer_method(method), "不该截走 {method}");
        }
    }
}
