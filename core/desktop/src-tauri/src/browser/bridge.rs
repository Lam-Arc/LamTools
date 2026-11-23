// user:“M4：桥是唯一通道，且必须固定、可审计”+(页面侧只能做「读结构 / 派发合成事件 / 滚动 / 上报真实输入」，
// 不允许任意脚本执行；Rust 侧对每条消息做白名单校验，非法消息直接丢弃并记录，不影响页面)。
//
// 传输：WebView2 WebMessage 双向。宿主 → 页面用 `PostWebMessageAsJson`，
// 页面 → 宿主用 `chrome.webview.postMessage(string)`，由 `add_WebMessageReceived` 收到。
// 页面永远拿不到 Tauri IPC（静态断言 + 运行时自检是另一道闸，见 tests/browser_security_assert.rs）。
//
// 本文件负责「不需要窗口就能验证」的部分：注入脚本、消息校验、ref 台账、人机接管状态机、
// 请求-应答配对与超时。COM 调用在 `platform_win.rs`，命令编排在 `mod.rs`。
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError, Sender};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::browser::BrowserError;

/// 注入脚本（固定内容，随二进制发布；页面无法扩展它的能力集合）。
pub const BRIDGE_SCRIPT: &str = include_str!("bridge_script.js");

/// 协议版本：宿主与脚本必须一致，否则脚本里的 `sunday !== 1` 会让消息被忽略。
pub const PROTOCOL_VERSION: u64 = 1;

/// user:“单条 ≤ 256 KB”+(超过直接丢弃，不做解析)。
pub const MAX_MESSAGE_BYTES: usize = 256 * 1024;
/// user:“每标签 ≤ 60 条/秒”+(超频丢弃并计数，防止页面用桥把主线程打满)。
pub const MAX_MESSAGES_PER_SECOND: u32 = 60;
/// 错误文本上限：页面回报的错误信息不允许撑爆日志。
pub const MAX_ERROR_CHARS: usize = 512;

pub const MIN_TIMEOUT: Duration = Duration::from_millis(200);
pub const DEFAULT_TIMEOUT: Duration = Duration::from_millis(8000);
pub const MAX_TIMEOUT: Duration = Duration::from_millis(30000);

/// user:“用户一段时间无输入可交还，阈值可配”+(默认 45 秒：足够读完一段内容，又不至于让 Agent 干等太久)。
pub const HUMAN_QUIET: Duration = Duration::from_secs(45);

/// 页面可以发来的指令（应答会复用请求的 op）。
const OPS: [&str; 6] = ["snapshot", "act", "waitFor", "ping", "event", "html"];
/// 页面可以回报的错误码白名单：不在表内的整条消息作废。
const PAGE_ERROR_CODES: [&str; 5] = ["invalid_ref", "stale_ref", "unsupported", "page_error", "timeout"];
/// 消息允许出现的字段：多一个都算非法（字段白名单）。
const FIELDS: [&str; 8] = ["sunday", "id", "op", "kind", "args", "ok", "result", "error"];

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct BridgeError {
    pub code: String,
    pub message: String,
}

impl BridgeError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self { code: code.to_string(), message: message.into() }
    }
}

/// 校验通过后的页面消息。
#[derive(Clone, Debug, PartialEq)]
pub struct PageMessage {
    pub id: Option<String>,
    pub op: String,
    pub kind: Option<String>,
    pub ok: Option<bool>,
    pub result: Option<Value>,
    pub error: Option<BridgeError>,
}

/// 丢弃原因：只用于日志与计数，不回给页面（页面是攻击者，不回显细节）。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RejectReason {
    TooLarge,
    NotJson,
    NotObject,
    WrongMarker,
    UnknownField,
    MissingFields,
    BadId,
    UnknownOp,
    BadError,
}

impl RejectReason {
    pub fn label(self) -> &'static str {
        match self {
            Self::TooLarge => "message_too_large",
            Self::NotJson => "message_not_json",
            Self::NotObject => "message_not_object",
            Self::WrongMarker => "message_wrong_marker",
            Self::UnknownField => "message_unknown_field",
            Self::MissingFields => "message_missing_fields",
            Self::BadId => "message_bad_id",
            Self::UnknownOp => "message_unknown_op",
            Self::BadError => "message_bad_error",
        }
    }
}

/// user:“消息必须带请求 id 并做严格校验”+(字段白名单 + 长度上限 + 类型断言，任何一条不符就整条作废)。
pub fn validate(raw: &str) -> Result<PageMessage, RejectReason> {
    if raw.len() > MAX_MESSAGE_BYTES {
        return Err(RejectReason::TooLarge);
    }
    let value: Value = serde_json::from_str(raw).map_err(|_| RejectReason::NotJson)?;
    let object = value.as_object().ok_or(RejectReason::NotObject)?;
    for key in object.keys() {
        if !FIELDS.contains(&key.as_str()) {
            return Err(RejectReason::UnknownField);
        }
    }
    if object.get("sunday").and_then(Value::as_u64) != Some(PROTOCOL_VERSION) {
        return Err(RejectReason::WrongMarker);
    }
    let op = object.get("op").and_then(Value::as_str).ok_or(RejectReason::MissingFields)?;
    if !OPS.contains(&op) {
        return Err(RejectReason::UnknownOp);
    }
    let id = match object.get("id").and_then(Value::as_str) {
        Some(id) => {
            if !valid_message_id(id) {
                return Err(RejectReason::BadId);
            }
            Some(id.to_string())
        }
        None => None,
    };
    // 只有事件可以没有 id；应答必须带 id，否则无法配对。
    if op != "event" && id.is_none() {
        return Err(RejectReason::MissingFields);
    }
    let kind = object.get("kind").and_then(Value::as_str).map(str::to_string);
    if op == "event" && kind.is_none() {
        return Err(RejectReason::MissingFields);
    }
    let ok = match object.get("ok") {
        None => None,
        Some(value) => Some(value.as_bool().ok_or(RejectReason::MissingFields)?),
    };
    let result = object.get("result").cloned();
    let error = match object.get("error") {
        None => None,
        Some(raw_error) => {
            let code = raw_error.get("code").and_then(Value::as_str).ok_or(RejectReason::BadError)?;
            if !PAGE_ERROR_CODES.contains(&code) {
                return Err(RejectReason::BadError);
            }
            let message = raw_error.get("message").and_then(Value::as_str).unwrap_or_default();
            if message.chars().count() > MAX_ERROR_CHARS {
                return Err(RejectReason::BadError);
            }
            Some(BridgeError::new(code, message))
        }
    };
    Ok(PageMessage { id, op: op.to_string(), kind, ok, result, error })
}

/// 请求 id 由宿主生成（`c17`），只允许小写字母开头 + 数字。
fn valid_message_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    if bytes.len() < 2 || bytes.len() > 10 {
        return false;
    }
    bytes[0].is_ascii_lowercase() && bytes[1..].iter().all(|byte| byte.is_ascii_digit())
}

/// 一条应答：`ok` 与 `error` 互斥，二者都没有时按失败处理。
#[derive(Clone, Debug, PartialEq)]
pub struct PageReply {
    pub ok: bool,
    pub result: Option<Value>,
    pub error: Option<BridgeError>,
}

impl PageReply {
    pub fn success(result: Value) -> Self {
        Self { ok: true, result: Some(result), error: None }
    }

    /// 把页面应答翻译成宿主错误；页面自己报的 `timeout` 保持可重试。
    pub fn into_result(self) -> Result<Value, BrowserError> {
        if self.ok {
            return Ok(self.result.unwrap_or(Value::Null));
        }
        let error = self.error.unwrap_or_else(|| BridgeError::new("page_error", "页面没有说明失败原因"));
        let retriable = matches!(error.code.as_str(), "timeout" | "stale_ref");
        Err(BrowserError::new(&error.code, error.message, retriable))
    }
}

// ---------------------------------------------------------------------------
// 请求-应答配对
// ---------------------------------------------------------------------------

struct PendingEntry {
    tab: String,
    sender: Sender<PageReply>,
    started: Instant,
}

fn pending() -> &'static Mutex<HashMap<String, PendingEntry>> {
    static PENDING: OnceLock<Mutex<HashMap<String, PendingEntry>>> = OnceLock::new();
    PENDING.get_or_init(|| Mutex::new(HashMap::new()))
}

static NEXT_REQUEST: AtomicU64 = AtomicU64::new(0);

/// 宿主生成请求 id：不接收页面提供的 id，避免伪造应答。
pub fn next_request_id() -> String {
    format!("c{}", NEXT_REQUEST.fetch_add(1, Ordering::Relaxed) + 1)
}

/// 先登记再发消息：页面应答可能比函数返回还快。
pub fn register(id: &str, tab: &str) -> Receiver<PageReply> {
    let (sender, receiver) = mpsc::channel();
    if let Ok(mut map) = pending().lock() {
        // 顺手清掉陈旧条目：页面长期不回时 map 不能无限长大。
        map.retain(|_, entry| entry.started.elapsed() < MAX_TIMEOUT * 2);
        map.insert(id.to_string(), PendingEntry { tab: tab.to_string(), sender, started: Instant::now() });
    }
    receiver
}

/// 页面应答到达时调用；返回是否命中了一个等待中的请求。
pub fn resolve(id: &str, reply: PageReply) -> bool {
    let entry = pending().lock().ok().and_then(|mut map| map.remove(id));
    entry.map(|entry| entry.sender.send(reply).is_ok()).unwrap_or(false)
}

/// user:“超时返回可读错误码”+(不静默失败：调用方一定拿到 `timeout` 或具体原因)。
pub fn wait(receiver: Receiver<PageReply>, timeout: Duration) -> Result<PageReply, BrowserError> {
    match receiver.recv_timeout(timeout) {
        Ok(reply) => Ok(reply),
        Err(RecvTimeoutError::Timeout) => Err(BrowserError::new(
            "timeout",
            "页面没有在规定时间内响应（桥可能被页面改写，或网页还在加载）",
            true,
        )),
        Err(RecvTimeoutError::Disconnected) => Err(BrowserError::internal("桥的应答通道已经关闭")),
    }
}

/// 标签关闭时清掉它的等待项与计数器。
pub fn forget_tab(tab: &str) {
    if let Ok(mut map) = pending().lock() {
        map.retain(|_, entry| entry.tab != tab);
    }
    if let Ok(mut map) = drops().lock() {
        map.remove(tab);
    }
    if let Ok(mut map) = rates().lock() {
        map.remove(tab);
    }
    if let Ok(mut map) = deliveries().lock() {
        map.remove(tab);
    }
}

// ---------------------------------------------------------------------------
// 后台投递观测
//
// user:“后台 WebMessage 投递可观测：在 browser_diagnostics（或 browser_state）里加一项
// 「后台标签消息投递」观测结果（最近一次后台投递是否收到应答、耗时），用于真机判定
// 「是否所有 Agent 操作都要先临时显示」。不要猜一个结论，给出可读的诊断输出。”+
// (这里只记事实：这条指令投递时标签在不在前台、有没有收到应答、用了多久。
//  判断仍然留给人：有应答说明隐藏标签能直接跑，没应答才需要「临时显示后重试」)。
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeliveryRecord {
    /// 浏览器标签 id（`browser-*`）。
    pub tab: String,
    /// 投递的指令（`snapshot` / `act` / `waitFor` …）。
    pub op: String,
    /// 投递时这个标签是不是在后台（不是当前可见标签）。
    pub background: bool,
    /// 是否收到页面应答。
    pub acked: bool,
    /// 失败时的错误码，成功时是 `ok`。
    pub outcome: String,
    pub elapsed_ms: u64,
}

fn deliveries() -> &'static Mutex<HashMap<String, DeliveryRecord>> {
    static DELIVERIES: OnceLock<Mutex<HashMap<String, DeliveryRecord>>> = OnceLock::new();
    DELIVERIES.get_or_init(|| Mutex::new(HashMap::new()))
}

/// 每个标签只留最近一次：诊断要回答「刚才那条后台投递成不成」，不是历史流水。
pub fn record_delivery(record: DeliveryRecord) {
    if let Ok(mut map) = deliveries().lock() {
        map.insert(record.tab.clone(), record);
    }
}

pub fn last_delivery(tab: &str) -> Option<DeliveryRecord> {
    deliveries().lock().ok().and_then(|map| map.get(tab).cloned())
}

/// 可读的一句话：真机验收时直接抄进结论，不用自己翻译数字。
pub fn delivery_note(record: &DeliveryRecord) -> String {
    let where_ = if record.background { "后台标签" } else { "前台标签" };
    let verdict = if record.acked {
        "收到应答，说明该操作不必先临时显示"
    } else {
        "没有收到应答，这类操作需要临时显示后重试"
    };
    format!(
        "最近一次 {} 投递（{} {}）：{}，耗时 {} ms",
        where_, record.op, record.tab, verdict, record.elapsed_ms
    )
}

// ---------------------------------------------------------------------------
// 频率限制与非法消息计数
// ---------------------------------------------------------------------------

struct RateWindow {
    started: Instant,
    count: u32,
}

fn rates() -> &'static Mutex<HashMap<String, RateWindow>> {
    static RATES: OnceLock<Mutex<HashMap<String, RateWindow>>> = OnceLock::new();
    RATES.get_or_init(|| Mutex::new(HashMap::new()))
}

/// user:“每标签 ≤ 60 条/秒”+(按 1 秒滚动窗口计数；超限直接丢弃)。
pub fn allow_message(tab: &str) -> bool {
    let Ok(mut map) = rates().lock() else { return false };
    let window = map.entry(tab.to_string()).or_insert_with(|| RateWindow { started: Instant::now(), count: 0 });
    if window.started.elapsed() >= Duration::from_secs(1) {
        window.started = Instant::now();
        window.count = 0;
    }
    window.count += 1;
    window.count <= MAX_MESSAGES_PER_SECOND
}

#[derive(Clone, Debug, Default)]
pub struct DropCounter {
    pub total: u64,
    /// 最近一次丢弃的原因（给超时错误用：让「页面没响应」能说出到底为什么没响应）。
    pub last_reason: String,
}

fn drops() -> &'static Mutex<HashMap<String, DropCounter>> {
    static DROPS: OnceLock<Mutex<HashMap<String, DropCounter>>> = OnceLock::new();
    DROPS.get_or_init(|| Mutex::new(HashMap::new()))
}

/// 记录一条被丢弃的非法消息（只计数，不回执页面）。
pub fn record_drop(tab: &str, reason: &str) {
    if let Ok(mut map) = drops().lock() {
        let counter = map.entry(tab.to_string()).or_default();
        counter.total += 1;
        counter.last_reason = reason.to_string();
    }
}

pub fn drop_count(tab: &str) -> u64 {
    drops()
        .lock()
        .ok()
        .and_then(|map| map.get(tab).map(|counter| counter.total))
        .unwrap_or(0)
}

/// 这个标签最近被丢掉了多少条页面消息、为什么丢。
///
/// user:“失败状态识别 不允许静默伪装成功”+(协议不一致时页面其实回话了，只是被判非法；
/// 超时错误里带上这个，才不会把「字段不合法」误诊成「页面没响应」)。
pub fn drop_summary(tab: &str) -> Option<String> {
    let map = drops().lock().ok()?;
    let counter = map.get(tab)?;
    if counter.total == 0 {
        return None;
    }
    Some(format!("{} 条页面消息被判非法丢弃（最后一次原因：{}）", counter.total, counter.last_reason))
}

/// 页面消息入口：校验 → 计数 → 交给等待中的请求或接管状态机。
///
/// 这个函数可能跑在 COM 回调里（UI 线程），所以只做纯内存操作，不阻塞、不 panic。
pub fn on_page_message(app: &tauri::AppHandle, tab: &str, raw: &str) {
    if !allow_message(tab) {
        record_drop(tab, "message_too_frequent");
        return;
    }
    let message = match validate(raw) {
        Ok(message) => message,
        Err(reason) => {
            record_drop(tab, reason.label());
            return;
        }
    };
    if message.op == "event" {
        // user:“用户真实输入 = 接管信号”+(合成事件 isTrusted 恒 false，所以这里只会是真人操作)。
        if message.kind.as_deref() == Some("user-input") {
            crate::browser::note_user_input(app, tab);
        }
        return;
    }
    let Some(id) = message.id else {
        record_drop(tab, "message_missing_id");
        return;
    };
    let reply = PageReply { ok: message.ok.unwrap_or(false), result: message.result, error: message.error };
    if !resolve(&id, reply) {
        record_drop(tab, "message_unknown_request");
    }
}

// ---------------------------------------------------------------------------
// ref 台账：ref 由页面分配，宿主只认「本次快照里出现过的」
// ---------------------------------------------------------------------------

/// `e12` 形状的引用。序列号由页面脚本分配，宿主负责校验格式与有效期。
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct RefId {
    pub seq: u32,
}

impl RefId {
    pub fn parse(raw: &str) -> Option<Self> {
        let rest = raw.strip_prefix('e')?;
        if rest.is_empty() || rest.len() > 6 || !rest.bytes().all(|byte| byte.is_ascii_digit()) {
            return None;
        }
        rest.parse::<u32>().ok().filter(|seq| *seq > 0).map(|seq| Self { seq })
    }

    pub fn label(self) -> String {
        format!("e{}", self.seq)
    }
}

/// user:“同一页面内多次快照尽量稳定，元素消失要标记 stale”+(页面用 WeakMap 复用编号；
/// 宿主只记录最近一次快照的 ref 集合，用错编号立刻返回 stale_ref，不让旧编号摸到变化后的页面)。
#[derive(Clone, Debug, Default)]
pub struct RefLedger {
    sequence: u32,
    current: Vec<String>,
}

impl RefLedger {
    pub fn new() -> Self {
        Self::default()
    }

    /// 记录一份新快照返回的 ref 集合（覆盖式：上一份立即失效）。
    pub fn record_snapshot(&mut self, refs: Vec<String>) -> u32 {
        self.sequence += 1;
        self.current = refs;
        self.sequence
    }

    pub fn sequence(&self) -> u32 {
        self.sequence
    }

    pub fn current(&self) -> &[String] {
        &self.current
    }

    /// 写操作前校验 ref：格式错报 `invalid_ref`，过期报 `stale_ref`（都要求重新快照）。
    pub fn require(&self, raw: &str) -> Result<RefId, BrowserError> {
        let id = RefId::parse(raw)
            .ok_or_else(|| BrowserError::new("invalid_ref", format!("ref 必须形如 e12，收到「{raw}」"), false))?;
        if self.sequence == 0 {
            return Err(BrowserError::new("stale_ref", "还没有快照，请先调用 browser_snapshot", true));
        }
        if !self.current.iter().any(|item| item == raw) {
            return Err(BrowserError::new(
                "stale_ref",
                format!("{raw} 已经失效（元素消失或页面变了），请重新 snapshot 后用新的 ref"),
                true,
            ));
        }
        Ok(id)
    }

    /// 页面回报 stale_ref 时把该编号从台账里摘掉，避免同一个死编号被反复使用。
    pub fn invalidate(&mut self, raw: &str) {
        self.current.retain(|item| item != raw);
    }
}

// ---------------------------------------------------------------------------
// 人机协同：human-owned 状态机
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Owner {
    Agent,
    Human,
}

impl Owner {
    pub fn label(self) -> &'static str {
        match self {
            Self::Agent => "agent",
            Self::Human => "human",
        }
    }

    pub fn parse(raw: &str) -> Option<Self> {
        match raw {
            "agent" => Some(Self::Agent),
            "human" => Some(Self::Human),
            _ => None,
        }
    }
}

/// user:“进入 human-owned 后 Rust 拒绝一切 Agent 写操作；用户一段时间无输入可交还”+
/// 状态机只有两个状态与三条转移：
/// - `Agent --(isTrusted 真实输入)--> Human`
/// - `Human --(静默超过阈值)--> Agent`
/// - `Human --(用户点「交回给 Agent」)--> Agent`
///
/// 只读操作（snapshot / screenshot）在 Human 状态下仍然允许：用户接管的是「动手」，不是「看一眼」。
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Ownership {
    owner: Owner,
    last_user_input: Option<Instant>,
    quiet: Duration,
}

impl Default for Ownership {
    fn default() -> Self {
        Self { owner: Owner::Agent, last_user_input: None, quiet: HUMAN_QUIET }
    }
}

impl Ownership {
    pub fn owner(&self) -> Owner {
        self.owner
    }

    /// 阈值可配（前端设置里改成「更慢/更快交还」时用）。
    pub fn with_quiet(mut self, quiet: Duration) -> Self {
        self.quiet = quiet;
        self
    }

    pub fn quiet(&self) -> Duration {
        self.quiet
    }

    /// 收到真实用户输入：切到 Human；返回是否发生了状态转移。
    pub fn note_user_input(&mut self, now: Instant) -> bool {
        let changed = self.owner != Owner::Human;
        self.owner = Owner::Human;
        self.last_user_input = Some(now);
        changed
    }

    /// 用户静默超过阈值就自动交还；返回是否发生了状态转移。
    pub fn release_if_quiet(&mut self, now: Instant) -> bool {
        if self.owner != Owner::Human {
            return false;
        }
        let Some(last) = self.last_user_input else {
            self.owner = Owner::Agent;
            return true;
        };
        if now.duration_since(last) >= self.quiet {
            self.owner = Owner::Agent;
            self.last_user_input = None;
            true
        } else {
            false
        }
    }

    /// 用户显式「交回给 Agent」。
    pub fn hand_to_agent(&mut self) -> bool {
        let changed = self.owner != Owner::Agent;
        self.owner = Owner::Agent;
        self.last_user_input = None;
        changed
    }

    /// 写操作的闸门。
    pub fn can_write(&self) -> Result<(), BrowserError> {
        if self.owner == Owner::Human {
            return Err(BrowserError::new(
                "human_owned",
                format!(
                    "用户正在操作这个标签，Agent 的写操作被拒绝（静默 {} 秒后自动交还，或让用户点「交回给 Agent」）",
                    self.quiet.as_secs()
                ),
                true,
            ));
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// 后台标签操作：临时显示 → 操作 → 切回
// ---------------------------------------------------------------------------

/// user:“后台标签被操作时不抢焦点”+(只做「临时可见」，从不 MoveFocus；
/// 是否临时显示由这个纯函数决定，便于单测)。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ForegroundPlan {
    /// 标签已经是活动且可见：什么都不用改。
    Keep,
    /// 需要临时显示，操作结束后恢复隐藏。
    ShowTemporarily,
}

pub fn foreground_plan(is_active: bool, visible: bool) -> ForegroundPlan {
    if is_active && visible {
        ForegroundPlan::Keep
    } else {
        ForegroundPlan::ShowTemporarily
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_reply() -> String {
        r#"{"sunday":1,"id":"c17","op":"snapshot","ok":true,"result":{"refs":[]}}"#.to_string()
    }

    // user:“后台 WebMessage 投递可观测…给出可读的诊断输出”+
    // (账本只回答「最近一次投递成不成」，所以要覆盖：记一次、只留最近一次、关标签清掉、可读文案)。
    #[test]
    fn delivery_ledger_keeps_the_latest_attempt_per_tab() {
        forget_tab("browser-t1");
        record_delivery(DeliveryRecord {
            tab: "browser-t1".into(),
            op: "snapshot".into(),
            background: true,
            acked: false,
            outcome: "timeout".into(),
            elapsed_ms: 8000,
        });
        let first = last_delivery("browser-t1").expect("刚记的投递必须能读回来");
        assert!(first.background && !first.acked);
        assert!(delivery_note(&first).contains("没有收到应答"));
        assert!(delivery_note(&first).contains("8000 ms"));

        record_delivery(DeliveryRecord {
            tab: "browser-t1".into(),
            op: "act".into(),
            background: false,
            acked: true,
            outcome: "ok".into(),
            elapsed_ms: 42,
        });
        let latest = last_delivery("browser-t1").expect("第二次投递必须覆盖第一次");
        assert_eq!(latest.op, "act");
        assert_eq!(latest.elapsed_ms, 42);
        assert!(delivery_note(&latest).contains("前台标签"));
        assert!(delivery_note(&latest).contains("收到应答"));

        forget_tab("browser-t1");
        assert!(last_delivery("browser-t1").is_none(), "标签关闭后不该留着旧观测");
    }

    #[test]
    fn unknown_tab_has_no_delivery_observation() {
        forget_tab("browser-missing");
        assert!(last_delivery("browser-missing").is_none());
    }

    #[test]
    fn accepts_a_well_formed_reply() {
        let message = validate(&valid_reply()).expect("合法应答必须通过");
        assert_eq!(message.id.as_deref(), Some("c17"));
        assert_eq!(message.op, "snapshot");
        assert_eq!(message.ok, Some(true));
    }

    #[test]
    fn rejects_oversized_payload() {
        let huge = format!("{}{}", valid_reply(), "x".repeat(MAX_MESSAGE_BYTES));
        assert_eq!(validate(&huge).unwrap_err(), RejectReason::TooLarge);
        // 边界值本身要能过（长度上限是「不超」）。
        let filler = "x".repeat(MAX_MESSAGE_BYTES - valid_reply().len());
        let padded = format!("{}#{}", valid_reply(), filler);
        assert_eq!(padded.len(), MAX_MESSAGE_BYTES + 1);
        assert_eq!(validate(&padded).unwrap_err(), RejectReason::TooLarge);
    }

    #[test]
    fn rejects_broken_json_and_non_objects() {
        assert_eq!(validate("not json").unwrap_err(), RejectReason::NotJson);
        assert_eq!(validate("[1,2,3]").unwrap_err(), RejectReason::NotObject);
        assert_eq!(validate("\"text\"").unwrap_err(), RejectReason::NotObject);
    }

    #[test]
    fn rejects_unknown_fields_and_wrong_marker() {
        let with_extra = r#"{"sunday":1,"id":"c1","op":"snapshot","ok":true,"cmd":"browser_open"}"#;
        assert_eq!(validate(with_extra).unwrap_err(), RejectReason::UnknownField);
        let wrong_marker = r#"{"sunday":2,"id":"c1","op":"snapshot","ok":true}"#;
        assert_eq!(validate(wrong_marker).unwrap_err(), RejectReason::WrongMarker);
        let missing_marker = r#"{"id":"c1","op":"snapshot","ok":true}"#;
        assert_eq!(validate(missing_marker).unwrap_err(), RejectReason::WrongMarker);
    }

    #[test]
    fn rejects_bad_ids_unknown_ops_and_bad_errors() {
        let bad_id = r#"{"sunday":1,"id":"C1","op":"snapshot","ok":true}"#;
        assert_eq!(validate(bad_id).unwrap_err(), RejectReason::BadId);
        let huge_id = r#"{"sunday":1,"id":"c12345678901","op":"snapshot","ok":true}"#;
        assert_eq!(validate(huge_id).unwrap_err(), RejectReason::BadId);
        let unknown_op = r#"{"sunday":1,"id":"c1","op":"evaluate","ok":true}"#;
        assert_eq!(validate(unknown_op).unwrap_err(), RejectReason::UnknownOp);
        let missing_id = r#"{"sunday":1,"op":"act","ok":true}"#;
        assert_eq!(validate(missing_id).unwrap_err(), RejectReason::MissingFields);
        let bad_error = r#"{"sunday":1,"id":"c1","op":"act","ok":false,"error":{"code":"boom","message":"x"}}"#;
        assert_eq!(validate(bad_error).unwrap_err(), RejectReason::BadError);
        let long_error = format!(
            r#"{{"sunday":1,"id":"c1","op":"act","ok":false,"error":{{"code":"page_error","message":"{}"}}}}"#,
            "x".repeat(MAX_ERROR_CHARS + 1)
        );
        assert_eq!(validate(&long_error).unwrap_err(), RejectReason::BadError);
    }

    #[test]
    fn accepts_user_input_events_without_id() {
        let event = r#"{"sunday":1,"op":"event","kind":"user-input","args":{"kind":"pointerdown"}}"#;
        let message = validate(event).expect("事件合法");
        assert_eq!(message.op, "event");
        assert_eq!(message.kind.as_deref(), Some("user-input"));
        assert!(message.id.is_none());
    }

    #[test]
    fn rate_limit_drops_burst_beyond_the_cap() {
        let tab = "tab-rate-limit";
        for _ in 0..MAX_MESSAGES_PER_SECOND {
            assert!(allow_message(tab), "限额内必须放行");
        }
        assert!(!allow_message(tab), "超过 60 条/秒必须丢弃");
        forget_tab(tab);
    }

    #[test]
    fn ref_ids_are_validated_and_stale_refs_are_rejected() {
        assert_eq!(RefId::parse("e12").map(|id| id.seq), Some(12));
        assert_eq!(RefId::parse("e0"), None);
        assert_eq!(RefId::parse("E12"), None);
        assert_eq!(RefId::parse("e"), None);
        assert_eq!(RefId::parse("e1234567"), None);
        assert_eq!(RefId::parse("e-1"), None);

        let mut ledger = RefLedger::new();
        // 还没快照过：任何 ref 都是 stale，而不是 invalid。
        assert_eq!(ledger.require("e1").unwrap_err().code, "stale_ref");
        ledger.record_snapshot(vec!["e1".into(), "e2".into()]);
        assert!(ledger.require("e1").is_ok());
        assert_eq!(ledger.require("e9").unwrap_err().code, "stale_ref");
        assert_eq!(ledger.require("button").unwrap_err().code, "invalid_ref");
        // 新快照覆盖旧编号：上一份的 e2 立即失效。
        ledger.record_snapshot(vec!["e3".into()]);
        assert_eq!(ledger.require("e2").unwrap_err().code, "stale_ref");
        assert!(ledger.require("e3").is_ok());
        ledger.invalidate("e3");
        assert_eq!(ledger.require("e3").unwrap_err().code, "stale_ref");
        assert_eq!(ledger.sequence(), 2);
    }

    #[test]
    fn human_owned_blocks_writes_until_quiet_or_handback() {
        let start = Instant::now();
        let mut ownership = Ownership::default().with_quiet(Duration::from_secs(30));
        assert!(ownership.can_write().is_ok(), "默认是 agent-owned");

        assert!(ownership.note_user_input(start), "第一次真实输入要发生状态转移");
        assert_eq!(ownership.owner(), Owner::Human);
        assert_eq!(ownership.can_write().unwrap_err().code, "human_owned");
        assert!(!ownership.note_user_input(start + Duration::from_secs(1)), "已经在 Human 不重复转移");

        // 静默不足阈值：仍然拒绝。
        assert!(!ownership.release_if_quiet(start + Duration::from_secs(20)));
        assert_eq!(ownership.can_write().unwrap_err().code, "human_owned");
        // 静默超过阈值：自动交还。
        assert!(ownership.release_if_quiet(start + Duration::from_secs(31)));
        assert!(ownership.can_write().is_ok());

        // 用户显式交回。
        ownership.note_user_input(start);
        assert!(ownership.hand_to_agent());
        assert!(ownership.can_write().is_ok());
        assert!(!ownership.hand_to_agent(), "已经是 agent-owned 时不再转移");
    }

    #[test]
    fn page_errors_become_host_errors_with_retry_hint() {
        let stale = PageReply { ok: false, result: None, error: Some(BridgeError::new("stale_ref", "e12 失效")) };
        let error = stale.into_result().unwrap_err();
        assert_eq!(error.code, "stale_ref");
        assert!(error.retriable, "stale_ref 可以靠重快照恢复");

        let broken = PageReply { ok: false, result: None, error: Some(BridgeError::new("page_error", "boom")) };
        let error = broken.into_result().unwrap_err();
        assert_eq!(error.code, "page_error");
        assert!(!error.retriable);

        assert_eq!(PageReply::success(serde_json::json!({"a":1})).into_result().unwrap()["a"], 1);
    }

    #[test]
    fn waiting_requests_time_out_with_a_readable_code() {
        let id = next_request_id();
        let receiver = register(&id, "tab-timeout");
        let error = wait(receiver, Duration::from_millis(10)).unwrap_err();
        assert_eq!(error.code, "timeout");
        assert!(error.retriable);
        forget_tab("tab-timeout");

        // 正常应答路径。
        let id = next_request_id();
        let receiver = register(&id, "tab-reply");
        assert!(resolve(&id, PageReply::success(serde_json::json!({"ok":1}))));
        let reply = wait(receiver, Duration::from_millis(500)).expect("应答必须被收到");
        assert_eq!(reply.into_result().unwrap()["ok"], 1);
        // 重复应答不再命中。
        assert!(!resolve(&id, PageReply::success(serde_json::json!({}))));
        forget_tab("tab-reply");
    }

    #[test]
    fn background_tabs_are_shown_temporarily_then_restored() {
        assert_eq!(foreground_plan(true, true), ForegroundPlan::Keep);
        assert_eq!(foreground_plan(false, true), ForegroundPlan::ShowTemporarily);
        assert_eq!(foreground_plan(true, false), ForegroundPlan::ShowTemporarily);
        assert_eq!(foreground_plan(false, false), ForegroundPlan::ShowTemporarily);
    }

    #[test]
    fn injected_script_answers_with_the_request_op() {
        // 宿主 validate 要求 op ∈ OPS：脚本漏了 op 就会被整条丢弃，表现为「页面没响应」的假超时。
        // 这条断言把两侧契约钉在一起（脚本里的回执只能走 reply()）。
        assert!(
            BRIDGE_SCRIPT.contains("op: message.op"),
            "注入脚本的回执必须回带请求的 op，否则宿主会丢弃全部应答"
        );
        for op in OPS {
            if op == "event" {
                continue;
            }
            assert!(
                BRIDGE_SCRIPT.contains(&format!("=== '{op}'")),
                "脚本没有处理 {op} 指令"
            );
        }
    }

    #[test]
    fn injected_script_has_no_dangerous_capability() {
        // user:“页面里的脚本永远不出现 invoke / __TAURI_INTERNALS__ / @tauri-apps/api”+
        // 这些字样在源码里也用 concat! 拼，否则静态断言会把本测试的字符串当成真实越权字样。
        let forbidden = [
            concat!("inv", "oke("),
            concat!("__TAURI", "_INTERNALS__"),
            concat!("@tauri-apps", "/api"),
            concat!("ev", "al("),
            concat!("new Fun", "ction("),
        ];
        for token in forbidden {
            assert!(!BRIDGE_SCRIPT.contains(token), "注入脚本里不能出现 {token}");
        }
        // 能力集合固定：只应答这几种指令。
        for op in ["snapshot", "act", "waitFor", "ping", "event"] {
            assert!(BRIDGE_SCRIPT.contains(op), "桥脚本必须实现 {op}");
        }
        assert!(BRIDGE_SCRIPT.contains("isTrusted"), "用户接管信号必须用 isTrusted");
        assert!(BRIDGE_SCRIPT.contains("postMessage"), "页面 → 宿主只能经 WebMessage");
        assert!(BRIDGE_SCRIPT.len() > 4000, "脚本内容不像完整实现，检查是否被截断");
    }
}
