// user:“权限默认全部拒绝”+(网页是不可信输入：摄像头/麦克风/定位/通知/剪贴板读默认 Deny，
// 前端显式授权后才按 host 放行；策略是纯逻辑，COM 回调只做执行器)。
//
// user:“证书错误不允许静默放行”+(默认阻断并给可读原因；「继续访问」必须走显式确认，且我们这边不记住)。
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use serde::{Deserialize, Serialize};

use crate::browser::BrowserError;

/// WebView2 `COREWEBVIEW2_PERMISSION_KIND` 的稳定映射（数值来自 webview2-com-sys 0.38.2 bindings）。
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum PermissionKind {
    Camera,
    Microphone,
    Geolocation,
    Notifications,
    ClipboardRead,
    OtherSensors,
    AutoPlay,
    FileReadWrite,
    LocalFonts,
    MultipleDownloads,
    MidiSystemExclusiveMessages,
    WindowManagement,
    Unknown,
}

impl PermissionKind {
    pub fn from_core(raw: i32) -> Self {
        match raw {
            1 => Self::Microphone,
            2 => Self::Camera,
            3 => Self::Geolocation,
            4 => Self::Notifications,
            5 => Self::OtherSensors,
            6 => Self::ClipboardRead,
            7 => Self::MultipleDownloads,
            8 => Self::FileReadWrite,
            9 => Self::AutoPlay,
            10 => Self::LocalFonts,
            11 => Self::MidiSystemExclusiveMessages,
            12 => Self::WindowManagement,
            _ => Self::Unknown,
        }
    }

    /// 对外（事件、状态、命令）用的稳定名字。
    pub fn label(&self) -> &'static str {
        match self {
            Self::Camera => "camera",
            Self::Microphone => "microphone",
            Self::Geolocation => "geolocation",
            Self::Notifications => "notifications",
            Self::ClipboardRead => "clipboard_read",
            Self::OtherSensors => "other_sensors",
            Self::AutoPlay => "autoplay",
            Self::FileReadWrite => "file_read_write",
            Self::LocalFonts => "local_fonts",
            Self::MultipleDownloads => "multiple_downloads",
            Self::MidiSystemExclusiveMessages => "midi_system_exclusive_messages",
            Self::WindowManagement => "window_management",
            Self::Unknown => "unknown",
        }
    }

    /// 给用户看的名字，出现在授权提示与拒绝提示里。
    pub fn display(&self) -> &'static str {
        match self {
            Self::Camera => "摄像头",
            Self::Microphone => "麦克风",
            Self::Geolocation => "位置信息",
            Self::Notifications => "通知",
            Self::ClipboardRead => "剪贴板内容",
            Self::OtherSensors => "传感器",
            Self::AutoPlay => "自动播放",
            Self::FileReadWrite => "本地文件读写",
            Self::LocalFonts => "本地字体列表",
            Self::MultipleDownloads => "批量下载",
            Self::MidiSystemExclusiveMessages => "MIDI 设备",
            Self::WindowManagement => "窗口管理",
            Self::Unknown => "未知权限",
        }
    }

    /// 权限矩阵的枚举全集：默认拒绝的断言要逐条覆盖，不能只测一两个。
    pub fn all() -> [PermissionKind; 13] {
        [
            Self::Camera,
            Self::Microphone,
            Self::Geolocation,
            Self::Notifications,
            Self::ClipboardRead,
            Self::OtherSensors,
            Self::AutoPlay,
            Self::FileReadWrite,
            Self::LocalFonts,
            Self::MultipleDownloads,
            Self::MidiSystemExclusiveMessages,
            Self::WindowManagement,
            Self::Unknown,
        ]
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum PermissionDecision {
    Allow,
    Deny,
}

impl PermissionDecision {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Allow => "allow",
            Self::Deny => "deny",
        }
    }
}

/// 放行粒度：仅本次 / 该站点。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PermissionScope {
    Once,
    Site,
}

impl PermissionScope {
    pub fn parse(raw: &str) -> Result<Self, BrowserError> {
        match raw {
            "once" => Ok(Self::Once),
            "site" => Ok(Self::Site),
            other => {
                Err(BrowserError::new("unsupported", format!("未知的授权范围：{other}"), false))
            }
        }
    }
}

/// user:“授权只按 host 记，只由 Rust 写”+(前端传不进来 scope=all 或通配符；没有命中就是拒绝)。
///
/// user:“授权表落盘”+(落到 `<lam_home>/core/config/browser-permissions.json`，前端只读；
/// 写失败必须报错，不能静默丢授权，所以先写盘成功再改内存)。
#[derive(Debug, Default)]
pub struct PermissionStore {
    grants: BTreeMap<String, GrantRecord>,
    path: Option<PathBuf>,
}

/// 一条站点授权：站点 + 权限 + 授予时间。
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct GrantRecord {
    pub host: String,
    pub kind: String,
    pub granted_at: String,
}

/// 磁盘上的文件形状（带版本号，便于以后迁移）。
#[derive(Serialize, Deserialize)]
struct PermissionsFile {
    version: u32,
    grants: Vec<GrantRecord>,
}

/// 用户配置目录（`<lam_home>`）：启动时由宿主注入，避免浏览器模块自己猜位置。
static CONFIG_ROOT: OnceLock<PathBuf> = OnceLock::new();

/// 授权文件的相对位置：相对 `<lam_home>`，属于用户配置而不是项目目录。
pub const PERMISSIONS_RELATIVE_PATH: &str = "core/config/browser-permissions.json";

pub fn set_config_root(root: PathBuf) {
    // 只接受第一次注入：多次启动路径不一致时以首个为准，避免中途换文件。
    let _ = CONFIG_ROOT.set(root);
}

/// 授权文件路径。没注入根目录时退回 `<可执行文件目录>/.lam`（便携版布局），仍然只落在应用的 `.lam` 下。
pub fn permissions_path() -> Option<PathBuf> {
    let root = match CONFIG_ROOT.get() {
        Some(root) => root.clone(),
        None => std::env::current_exe().ok()?.parent()?.join(".lam"),
    };
    Some(root.join(PERMISSIONS_RELATIVE_PATH))
}

fn grant_key(host: &str, kind: &str) -> String {
    format!("{host}|{kind}")
}

/// 秒级时间戳 → `YYYY-MM-DDTHH:MM:SSZ`（不引入额外依赖，纯函数可单测）。
pub fn iso_from_unix(seconds: u64) -> String {
    let days = (seconds / 86_400) as i64;
    let rest = seconds % 86_400;
    let (hour, minute, second) = (rest / 3600, (rest % 3600) / 60, rest % 60);
    // Howard Hinnant 的 civil_from_days 算法（1970-01-01 起算，无闰秒）。
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { y + 1 } else { y };
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")
}

fn now_record(host: &str, kind: PermissionKind) -> GrantRecord {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs())
        .unwrap_or(0);
    GrantRecord {
        host: host.to_string(),
        kind: kind.label().to_string(),
        granted_at: iso_from_unix(seconds),
    }
}

fn io_error(action: &str, path: &Path, error: impl std::fmt::Display) -> BrowserError {
    BrowserError::new("internal", format!("{action}失败（{}）：{error}", path.display()), true)
}

/// 读授权表：文件不存在视为空表；内容损坏时不猜，按空表处理（全部拒绝，fail-closed）。
pub fn load_grants(path: &Path) -> Result<Vec<GrantRecord>, BrowserError> {
    let raw = match std::fs::read_to_string(path) {
        Ok(raw) => raw,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => return Err(io_error("读取站点授权", path, error)),
    };
    let parsed: PermissionsFile = serde_json::from_str(&raw)
        .map_err(|error| BrowserError::new("internal", format!("站点授权文件格式不正确，已按「全部拒绝」处理：{error}"), true))?;
    Ok(parsed.grants)
}

/// 写授权表：先写临时文件再原子替换，避免半截文件把已有授权读废。
pub fn save_grants(path: &Path, grants: &[GrantRecord]) -> Result<(), BrowserError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| io_error("创建授权目录", parent, error))?;
    }
    let payload = PermissionsFile { version: 1, grants: grants.to_vec() };
    let body = serde_json::to_string_pretty(&payload)
        .map_err(|error| BrowserError::new("internal", format!("站点授权无法序列化：{error}"), false))?;
    let temporary = path.with_extension("json.tmp");
    std::fs::write(&temporary, body).map_err(|error| io_error("写入站点授权", &temporary, error))?;
    std::fs::rename(&temporary, path).map_err(|error| io_error("保存站点授权", path, error))
}

impl PermissionStore {
    /// 不带持久化（单测与「尚未知道配置目录」的早期阶段）。
    pub fn new() -> Self {
        Self::default()
    }

    /// 从 `<lam_home>/core/config/browser-permissions.json` 读入；读不到就是空表（全部拒绝）。
    pub fn load() -> Self {
        let Some(path) = permissions_path() else { return Self::new() };
        let grants = load_grants(&path)
            .unwrap_or_default()
            .into_iter()
            .map(|record| (grant_key(&record.host, &record.kind), record))
            .collect();
        Self { grants, path: Some(path) }
    }

    pub fn persistence_path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    fn records(&self) -> Vec<GrantRecord> {
        self.grants.values().cloned().collect()
    }

    /// 先写盘再改内存：写失败就返回错误，权限保持「未授予」。
    fn commit(&mut self, next: BTreeMap<String, GrantRecord>) -> Result<(), BrowserError> {
        if let Some(path) = self.path.clone() {
            let mut records = next.values().cloned().collect::<Vec<_>>();
            records.sort_by(|a, b| (a.host.as_str(), a.kind.as_str()).cmp(&(b.host.as_str(), b.kind.as_str())));
            save_grants(&path, &records)?;
        }
        self.grants = next;
        Ok(())
    }

    pub fn decide(&self, host: &str, kind: PermissionKind) -> PermissionDecision {
        match self.grants.get(&grant_key(host, kind.label())) {
            Some(_) => PermissionDecision::Allow,
            None => PermissionDecision::Deny,
        }
    }

    pub fn grant(&mut self, host: &str, kind: PermissionKind) -> Result<(), BrowserError> {
        let mut next = self.grants.clone();
        let record = now_record(host, kind);
        next.insert(grant_key(host, kind.label()), record);
        self.commit(next)
    }

    pub fn revoke(&mut self, host: &str, kind: PermissionKind) -> Result<(), BrowserError> {
        let mut next = self.grants.clone();
        next.remove(&grant_key(host, kind.label()));
        self.commit(next)
    }

    /// 清站数据时连带撤掉该 host 的授权（并同步落盘），避免「清了数据但摄像头还开着」。
    pub fn clear_host(&mut self, host: &str) -> Result<(), BrowserError> {
        let prefix = format!("{host}|");
        let mut next = self.grants.clone();
        next.retain(|key, _| !key.starts_with(&prefix));
        self.commit(next)
    }

    pub fn records_snapshot(&self) -> Vec<GrantRecord> {
        let mut records = self.records();
        records.sort_by(|a, b| (a.host.as_str(), a.kind.as_str()).cmp(&(b.host.as_str(), b.kind.as_str())));
        records
    }

    pub fn len(&self) -> usize {
        self.grants.len()
    }

    pub fn is_empty(&self) -> bool {
        self.grants.is_empty()
    }
}

/// 上报给前端的授权请求文案：必须说清「谁、要什么、默认会怎样」。
pub fn permission_request_message(host: &str, kind: PermissionKind, user_initiated: bool) -> String {
    let trigger = if user_initiated { "" } else { "（页面自动发起）" };
    format!("{host} 想要使用{}{trigger}，默认已拒绝", kind.display())
}

/// 拒绝后的可见提示：不能静默，用户要看得懂发生了什么、去哪里改。
pub fn permission_denied_message(host: &str, kind: PermissionKind) -> String {
    format!("已拒绝 {} 使用{}。需要时可在标签菜单里重新授权", host, kind.display())
}

// ---------------------------------------------------------------------------
// 证书错误
// ---------------------------------------------------------------------------

/// `COREWEBVIEW2_WEB_ERROR_STATUS` 的证书相关取值 → 可读原因。
pub fn certificate_error_text(status: i32) -> &'static str {
    match status {
        1 => "证书上的域名与访问的站点不一致",
        2 => "证书已过期",
        3 => "客户端证书包含错误",
        4 => "证书已被吊销",
        5 => "证书无效或不被信任",
        _ => "无法验证该站点的安全证书",
    }
}

/// 阻断页文案：域名 + 原因 + 下一步，不出现裸错误码。
pub fn certificate_error_message(host: &str, status: i32) -> String {
    format!(
        "{} 的安全证书有问题：{}。已阻止继续加载，确认了解风险后才能继续访问。",
        host,
        certificate_error_text(status)
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_permission_kind_is_denied_by_default() {
        // user:“权限矩阵：默认全部拒绝”+(逐条覆盖，含 unknown，防止某个 kind 漏掉默认值)。
        let store = PermissionStore::new();
        for kind in PermissionKind::all() {
            assert_eq!(
                store.decide("example.com", kind),
                PermissionDecision::Deny,
                "{} 默认必须是拒绝",
                kind.label()
            );
        }
        assert!(store.is_empty());
    }

    #[test]
    fn grants_are_scoped_to_one_host_and_one_kind() {
        let mut store = PermissionStore::new();
        store.grant("example.com", PermissionKind::Camera).unwrap();
        assert_eq!(store.decide("example.com", PermissionKind::Camera), PermissionDecision::Allow);
        // 同一 host 的另一类权限不继承
        assert_eq!(store.decide("example.com", PermissionKind::Microphone), PermissionDecision::Deny);
        // 同一类权限不跨 host
        assert_eq!(store.decide("other.com", PermissionKind::Camera), PermissionDecision::Deny);
        // 子域不继承父域授权
        assert_eq!(store.decide("www.example.com", PermissionKind::Camera), PermissionDecision::Deny);
    }

    #[test]
    fn wildcard_and_empty_hosts_do_not_grant_anything() {
        // user:“通配符不生效”+(避免「允许 * 」这种请求把矩阵打穿)。
        let mut store = PermissionStore::new();
        store.grant("*", PermissionKind::Camera).unwrap();
        store.grant("", PermissionKind::Camera).unwrap();
        assert_eq!(store.decide("example.com", PermissionKind::Camera), PermissionDecision::Deny);
        assert_eq!(store.decide("*", PermissionKind::Camera), PermissionDecision::Allow, "只对字面量生效");
    }

    #[test]
    fn revoking_and_clearing_a_host_restores_deny() {
        let mut store = PermissionStore::new();
        store.grant("example.com", PermissionKind::Camera).unwrap();
        store.grant("example.com", PermissionKind::Microphone).unwrap();
        store.grant("other.com", PermissionKind::Camera).unwrap();
        store.revoke("example.com", PermissionKind::Microphone).unwrap();
        assert_eq!(store.decide("example.com", PermissionKind::Microphone), PermissionDecision::Deny);
        store.clear_host("example.com").unwrap();
        assert_eq!(store.decide("example.com", PermissionKind::Camera), PermissionDecision::Deny);
        assert_eq!(store.decide("other.com", PermissionKind::Camera), PermissionDecision::Allow, "别的站点不受影响");
        assert_eq!(store.len(), 1);
    }

    #[test]
    fn scope_parsing_is_strict() {
        assert_eq!(PermissionScope::parse("once").unwrap(), PermissionScope::Once);
        assert_eq!(PermissionScope::parse("site").unwrap(), PermissionScope::Site);
        assert_eq!(PermissionScope::parse("always").unwrap_err().code, "unsupported");
    }

    #[test]
    fn permission_kinds_round_trip_core_values() {
        // 数值取自 WebView2 常量表，改错会让默认拒绝落到别的 kind 上。
        let cases = [
            (1, PermissionKind::Microphone),
            (2, PermissionKind::Camera),
            (3, PermissionKind::Geolocation),
            (4, PermissionKind::Notifications),
            (5, PermissionKind::OtherSensors),
            (6, PermissionKind::ClipboardRead),
            (8, PermissionKind::FileReadWrite),
            (99, PermissionKind::Unknown),
        ];
        for (raw, expected) in cases {
            assert_eq!(PermissionKind::from_core(raw), expected, "{raw}");
            assert!(!expected.label().is_empty());
            assert!(!expected.display().is_empty());
        }
    }

    #[test]
    fn messages_are_human_readable() {
        let request = permission_request_message("example.com", PermissionKind::Camera, true);
        assert!(request.contains("example.com") && request.contains("摄像头") && request.contains("默认已拒绝"));
        assert!(permission_request_message("example.com", PermissionKind::Microphone, false).contains("自动发起"));
        let denied = permission_denied_message("example.com", PermissionKind::Geolocation);
        assert!(denied.contains("位置信息") && denied.contains("重新授权"));
    }

    #[test]
    fn certificate_errors_are_explained_not_dumped() {
        for status in [1, 2, 3, 4, 5, 4242] {
            let text = certificate_error_text(status);
            assert!(!text.is_empty());
            assert!(!text.contains("0x"), "不能把裸错误码丢给用户：{text}");
        }
        let message = certificate_error_message("expired.badssl.com", 2);
        assert!(message.contains("expired.badssl.com"));
        assert!(message.contains("已过期"));
        assert!(message.contains("继续访问"));
    }
    #[test]
    fn iso_time_is_readable_and_utc() {
        assert_eq!(iso_from_unix(0), "1970-01-01T00:00:00Z");
        assert_eq!(iso_from_unix(1_700_000_000), "2023-11-14T22:13:20Z");
        // 闰日
        assert_eq!(iso_from_unix(1_709_164_800), "2024-02-29T00:00:00Z");
    }

    #[test]
    fn grants_persist_to_the_permissions_file() {
        let dir = std::env::temp_dir().join(format!("sunday-perm-{}-a", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let path = dir.join("core/config/browser-permissions.json");
        let mut store = PermissionStore { path: Some(path.clone()), ..Default::default() };
        store.grant("example.com", PermissionKind::Camera).unwrap();
        assert_eq!(store.decide("example.com", PermissionKind::Camera), PermissionDecision::Allow);

        let raw = std::fs::read_to_string(&path).unwrap();
        assert!(raw.contains("\"version\": 1"), "{raw}");
        assert!(raw.contains("\"host\": \"example.com\""), "结构要能表达站点：{raw}");
        assert!(raw.contains("\"kind\": \"camera\""), "结构要能表达权限：{raw}");
        assert!(raw.contains("\"grantedAt\":"), "结构要能表达授予时间：{raw}");

        // 重新读盘后仍然放行，撤销后同步落盘
        let records = load_grants(&path).unwrap();
        let mut reloaded = PermissionStore {
            path: Some(path.clone()),
            grants: records.into_iter().map(|record| (grant_key(&record.host, &record.kind), record)).collect(),
        };
        assert_eq!(reloaded.decide("example.com", PermissionKind::Camera), PermissionDecision::Allow);
        reloaded.clear_host("example.com").unwrap();
        assert_eq!(reloaded.decide("example.com", PermissionKind::Camera), PermissionDecision::Deny);
        assert!(load_grants(&path).unwrap().is_empty(), "撤销必须同步落盘");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_failed_write_is_reported_instead_of_silently_dropping_the_grant() {
        // 授权文件的父路径是普通文件 → 建目录必然失败
        let dir = std::env::temp_dir().join(format!("sunday-perm-{}-b", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let blocker = dir.join("core");
        std::fs::write(&blocker, b"not a directory").unwrap();

        let mut store = PermissionStore {
            path: Some(blocker.join("config/browser-permissions.json")),
            ..Default::default()
        };
        let error = store.grant("example.com", PermissionKind::Camera).unwrap_err();
        assert_eq!(error.code, "internal");
        assert!(!error.message.is_empty());
        // 写盘失败时内存里也不能留下「已授权」：内存与磁盘必须一致
        assert_eq!(store.decide("example.com", PermissionKind::Camera), PermissionDecision::Deny);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
