// user:“内置浏览器不能用主界面那份 profile”+(normal 也是独立目录 `<app data>/webview2/browser`：
// 与主 webview 共用默认 profile 时，「清除站点数据」会把 Sunday 自己的 localStorage/IndexedDB 一起扫掉，
// 那是数据事故而不是体验问题；顺带也让站点的 Cookie 指纹关联不到主界面上下文)。
//
// user:“失败后的降级方案需要重新批准，不自动接受 C”+(临时会话必须真隔离：normal/incognito/自定义目录三态，
// 一律在创建 controller 之前通过 `WebviewBuilder::data_directory` / `.incognito(true)` 生效；
// controller 建好之后无法回填，所以 M2 只做「创建前决定」，没有「创建后改 profile」的命令)。
//
// 已核实（不要重复验证）：tauri 2.11.5 的 `WebviewBuilder` 支持 `.data_directory(PathBuf)` 与 `.incognito(bool)`
// （tauri `src/webview/mod.rs`:963 / :997），Windows 后端经 wry `webview2/mod.rs`:138 → :396 的
// `ICoreWebView2Environment10` / `SetIsInPrivateModeEnabled` 真实生效；每个不同的 data directory 会得到独立的
// WebView2 Environment（tauri-runtime-wry `lib.rs`:4793 用它作 key），也就意味着独立的 cookie/存储与额外的进程内存。
use std::path::{Component, Path, PathBuf};

use serde::Serialize;

use crate::browser::BrowserError;

/// user:“临时会话/自定义目录先留接缝”+(三态是命令与状态的对外契约，M2 起三态都真正生效)。
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub enum BrowserProfile {
    /// 共享持久会话：`<app data>/webview2/browser`（独立于主 webview 的默认 profile）。
    Normal,
    /// WebView2 InPrivate（`SetIsInPrivateModeEnabled`）：关闭即不落盘，重启不恢复。
    Incognito,
    /// 调用方显式指定的独立 user data folder。M2 只作为分组能力与 E1–E4 实验入口，不对普通用户暴露。
    Custom { dir: PathBuf },
}

impl BrowserProfile {
    /// 从命令参数解析；未知取值直接报错，不做「猜一个最接近的」。
    pub fn parse(raw: &str) -> Result<Self, BrowserError> {
        match raw {
            "" | "normal" => Ok(Self::Normal),
            "incognito" => Ok(Self::Incognito),
            other => {
                if other.contains(['/', '\\']) {
                    Ok(Self::Custom { dir: PathBuf::from(other) })
                } else {
                    Err(BrowserError::new("invalid_profile", format!("未知会话类型：{other}"), false))
                }
            }
        }
    }

    pub fn label(&self) -> String {
        match self {
            Self::Normal => "normal".to_string(),
            Self::Incognito => "incognito".to_string(),
            Self::Custom { dir } => format!("custom:{}", dir.to_string_lossy()),
        }
    }

    /// 只在创建 webview **之前**可用的映射，绝不能在 controller 建好之后套用。
    pub fn resolve(&self, app_data: &Path) -> Result<ProfileEnvironment, BrowserError> {
        Ok(match self {
            // user:“normal 改成独立目录”+(行为变化：以前不传 data_directory，等于和主界面共用默认 profile)。
            Self::Normal => ProfileEnvironment {
                data_directory: Some(default_browser_dir(app_data)),
                incognito: false,
            },
            Self::Incognito => ProfileEnvironment { data_directory: None, incognito: true },
            Self::Custom { dir } => ProfileEnvironment {
                data_directory: Some(resolve_custom_dir(dir, app_data)?),
                incognito: false,
            },
        })
    }

    /// user:“重启恢复：normal 按 URL 恢复、临时不恢复、custom 按 URL 恢复并标注目录”+(策略是纯函数，前端镜像同一份规则)。
    pub fn restore_plan(&self) -> RestorePlan {
        match self {
            // 临时会话关闭即销毁，重启恢复等于凭空造一个「看起来还在」的标签，所以不恢复。
            Self::Incognito => RestorePlan::Skip,
            Self::Normal | Self::Custom { .. } => RestorePlan::RestoreByUrl,
        }
    }

    /// 恢复时要标注的所属目录（normal 与临时会话没有目录标注）。
    pub fn restore_note(&self) -> Option<String> {
        match self {
            Self::Normal | Self::Incognito => None,
            Self::Custom { dir } => Some(dir.to_string_lossy().to_string()),
        }
    }

    /// 是否跨重启保存登录态。临时会话是唯一的例外。
    pub fn is_persistent(&self) -> bool {
        !matches!(self, Self::Incognito)
    }
}

/// user:“重启恢复”+(只回答「要不要按 URL 恢复」，恢复动作本身仍走前端布局模型)。
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub enum RestorePlan {
    RestoreByUrl,
    Skip,
}

/// 交给 `WebviewBuilder` 的两个参数（`data_directory` / `incognito`）。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProfileEnvironment {
    pub data_directory: Option<PathBuf>,
    pub incognito: bool,
}

/// 方案 3.5 指定的浏览器 user data folder：`<app data>/webview2/browser`。
pub fn default_browser_dir(app_data: &Path) -> PathBuf {
    app_data.join("webview2").join("browser")
}

fn invalid_dir(message: impl Into<String>) -> BrowserError {
    BrowserError::new("invalid_profile_dir", message, false)
}

/// 相对目录落到应用数据目录下；绝对目录按原样使用；含 `..` 或空目录一律拒绝（不允许逃逸）。
fn resolve_custom_dir(dir: &Path, app_data: &Path) -> Result<PathBuf, BrowserError> {
    if dir.as_os_str().is_empty() {
        return Err(invalid_dir("会话目录不能为空"));
    }
    if dir.components().any(|component| matches!(component, Component::ParentDir)) {
        return Err(invalid_dir("会话目录不能包含 .."));
    }
    if dir.components().any(|component| matches!(component, Component::Prefix(_) | Component::RootDir)) {
        // 绝对路径：要求至少两级（拒绝 `C:\` 这种盘根，避免把整个磁盘当 profile）。
        let depth = dir.components().filter(|component| matches!(component, Component::Normal(_))).count();
        if depth < 1 {
            return Err(invalid_dir("会话目录不能是磁盘根目录"));
        }
        return Ok(dir.to_path_buf());
    }
    Ok(app_data.join(dir))
}

// ---------------------------------------------------------------------------
// 站数据清理（按 host）
// ---------------------------------------------------------------------------

/// user:“站数据清理只清存储，缓存不动”+(用户 2026-11-16 拍板：清 Cookie / localStorage / IndexedDB /
/// Service Worker 等存储类数据，缓存资源一律不碰，所以从缓存打开的旧页面不会自动退出登录)。
///
/// 这个常量就是「清理请求可以包含哪些目标」的白名单，单测据此断言清理请求永不包含缓存类目标。
pub const STORAGE_TARGETS: [&str; 4] = ["cookies", "local_storage", "indexed_db", "service_worker"];

/// 缓存类目标：显式列出并被排除，用来断言「清理请求与缓存目标不相交」。
pub const CACHE_TARGETS: [&str; 2] = ["disk_cache", "cache_storage"];

/// 要清哪几类存储：命令只允许选择存储类目标。
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct SiteDataKinds {
    pub cookies: bool,
    pub storage: bool,
}

impl SiteDataKinds {
    pub fn all() -> Self {
        Self { cookies: true, storage: true }
    }

    pub fn none() -> Self {
        Self { cookies: false, storage: false }
    }

    /// 空列表等价于「存储类全清」：前端不做选择时就是想要一次干净退出登录。
    /// 传缓存类目标会被明确拒绝，而不是被静默忽略。
    pub fn parse(raw: Option<&[String]>) -> Result<Self, BrowserError> {
        let Some(raw) = raw else { return Ok(Self::all()) };
        if raw.is_empty() {
            return Ok(Self::all());
        }
        let mut kinds = Self::none();
        for item in raw {
            match item.as_str() {
                "cookies" => kinds.cookies = true,
                "storage" | "local_storage" | "indexed_db" | "service_worker" => kinds.storage = true,
                other if CACHE_TARGETS.contains(&other) || other == "cache" => {
                    return Err(BrowserError::new(
                        "unsupported",
                        "站数据清理只清登录与存储，不清理缓存（缓存资源保持不动）",
                        false,
                    ))
                }
                other => {
                    return Err(BrowserError::new(
                        "unsupported",
                        format!("未知的清理类型：{other}"),
                        false,
                    ))
                }
            }
        }
        Ok(kinds)
    }

    pub fn is_empty(&self) -> bool {
        !self.cookies && !self.storage
    }

    /// 实际下发给平台层的目标：只会是 `STORAGE_TARGETS` 里的成员。
    pub fn targets(&self) -> Vec<&'static str> {
        let mut targets = Vec::new();
        if self.cookies {
            targets.push("cookies");
        }
        if self.storage {
            targets.extend(["local_storage", "indexed_db", "service_worker"]);
        }
        targets
    }
}

/// 把「地址栏里那一串」收敛成用于匹配的 host：去掉协议、路径、端口、末尾点，统一小写。
pub fn normalize_host(raw: &str) -> Option<String> {
    let text = raw.trim();
    if text.is_empty() {
        return None;
    }
    let rest = match text.split_once("://") {
        Some((_, rest)) => rest,
        None => text,
    };
    // user:“user:pass@host 这种也认”+(凭据前缀不属于 host)。
    let rest = rest.rsplit_once('@').map(|(_, after)| after).unwrap_or(rest);
    let host = rest.split(['/', '?', '#']).next().unwrap_or(rest);
    let host = match host.rsplit_once(':') {
        Some((name, port)) if !port.is_empty() && port.chars().all(|c| c.is_ascii_digit()) => name,
        _ => host,
    };
    let host = host.trim().trim_matches('.').to_ascii_lowercase();
    if host.is_empty() || host.len() > 253 {
        return None;
    }
    if host.contains(char::is_whitespace) || host.contains(['/', '\\', '@', '"', '\'', '<', '>', '|', '*']) {
        return None;
    }
    Some(host)
}

/// 命令参数里的 host：非法时按 `invalid_url` 拒绝，不静默当成「全清」。
pub fn require_host(raw: &str) -> Result<String, BrowserError> {
    normalize_host(raw).ok_or_else(|| BrowserError::new("invalid_url", "这个站点地址无法识别", false))
}

/// user:“站数据清理的 host 匹配”+(cookie 的 Domain 可能带前导点、可能是父域；三种关系任一成立就算这个站点的数据)。
pub fn cookie_domain_matches(cookie_domain: &str, host: &str) -> bool {
    let (Some(cookie), Some(host)) = (normalize_host(cookie_domain), normalize_host(host)) else {
        return false;
    };
    cookie == host
        || host.ends_with(&format!(".{cookie}"))
        || cookie.ends_with(&format!(".{host}"))
}

/// 清理时用来枚举 cookie 的两个来源地址（安全与非安全协议各一次，HttpOnly/Secure 都能覆盖）。
pub fn cookie_sources(host: &str) -> Vec<String> {
    vec![format!("https://{host}/"), format!("http://{host}/")]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn app_data() -> PathBuf {
        PathBuf::from(r"C:\Users\Example\AppData\Roaming\Sunday")
    }

    #[test]
    fn normal_uses_its_own_user_data_folder() {
        // user:“清除站点数据不能扫掉 Sunday 自己的 localStorage”+(行为变化回归：normal 必须有独立目录)。
        let environment = BrowserProfile::Normal.resolve(&app_data()).unwrap();
        assert_eq!(environment.data_directory, Some(default_browser_dir(&app_data())));
        assert!(!environment.incognito);
        assert_eq!(default_browser_dir(&app_data()), app_data().join("webview2").join("browser"));
    }

    #[test]
    fn incognito_maps_to_inprivate_without_a_custom_directory() {
        let environment = BrowserProfile::Incognito.resolve(&app_data()).unwrap();
        assert_eq!(environment.data_directory, None);
        assert!(environment.incognito);
    }

    #[test]
    fn custom_relative_directory_lands_under_app_data() {
        let profile = BrowserProfile::Custom { dir: PathBuf::from("webview2/temp-1") };
        let environment = profile.resolve(&app_data()).unwrap();
        assert_eq!(environment.data_directory, Some(app_data().join("webview2").join("temp-1")));
        assert!(!environment.incognito);
    }

    #[test]
    fn custom_absolute_directory_is_used_as_is() {
        let profile = BrowserProfile::Custom { dir: PathBuf::from(r"D:\profiles\temp-2") };
        let environment = profile.resolve(&app_data()).unwrap();
        assert_eq!(environment.data_directory, Some(PathBuf::from(r"D:\profiles\temp-2")));
    }

    #[test]
    fn custom_directory_rejects_escapes_and_roots() {
        for dir in ["../escape", "a/../../escape", ""] {
            let profile = BrowserProfile::Custom { dir: PathBuf::from(dir) };
            let error = profile.resolve(&app_data()).unwrap_err();
            assert_eq!(error.code, "invalid_profile_dir", "{dir}");
        }
        let root = BrowserProfile::Custom { dir: PathBuf::from(r"C:\") };
        assert_eq!(root.resolve(&app_data()).unwrap_err().code, "invalid_profile_dir");
    }

    #[test]
    fn parse_accepts_only_known_names_or_paths() {
        assert_eq!(BrowserProfile::parse("").unwrap(), BrowserProfile::Normal);
        assert_eq!(BrowserProfile::parse("normal").unwrap(), BrowserProfile::Normal);
        assert_eq!(BrowserProfile::parse("incognito").unwrap(), BrowserProfile::Incognito);
        assert_eq!(
            BrowserProfile::parse("webview2/temp-9").unwrap(),
            BrowserProfile::Custom { dir: PathBuf::from("webview2/temp-9") }
        );
        assert_eq!(BrowserProfile::parse("mystery").unwrap_err().code, "invalid_profile");
    }

    #[test]
    fn labels_are_stable_for_state_reporting() {
        assert_eq!(BrowserProfile::Normal.label(), "normal");
        assert_eq!(BrowserProfile::Incognito.label(), "incognito");
        assert!(BrowserProfile::Custom { dir: PathBuf::from("x") }.label().starts_with("custom:"));
    }

    #[test]
    fn incognito_tabs_are_never_restored() {
        // user:“临时标签不恢复”+(重启后凭空出现一个临时标签等于伪造隔离)。
        assert_eq!(BrowserProfile::Incognito.restore_plan(), RestorePlan::Skip);
        assert!(!BrowserProfile::Incognito.is_persistent());
        assert_eq!(BrowserProfile::Normal.restore_plan(), RestorePlan::RestoreByUrl);
        assert!(BrowserProfile::Normal.is_persistent());
        let custom = BrowserProfile::Custom { dir: PathBuf::from("webview2/temp-3") };
        assert_eq!(custom.restore_plan(), RestorePlan::RestoreByUrl, "custom 按 URL 恢复");
        assert_eq!(custom.restore_note().as_deref(), Some("webview2/temp-3"), "恢复时标注所属目录");
        assert_eq!(BrowserProfile::Normal.restore_note(), None);
    }

    #[test]
    fn site_data_kinds_default_to_everything() {
        assert_eq!(SiteDataKinds::parse(None).unwrap(), SiteDataKinds::all());
        assert_eq!(SiteDataKinds::parse(Some(&[])).unwrap(), SiteDataKinds::all());
        let cookies_only = SiteDataKinds::parse(Some(&["cookies".to_string()])).unwrap();
        assert_eq!(cookies_only, SiteDataKinds { cookies: true, storage: false });
        let error = SiteDataKinds::parse(Some(&["passwords".to_string()])).unwrap_err();
        assert_eq!(error.code, "unsupported");
        assert!(SiteDataKinds::all().cookies && SiteDataKinds::all().storage);
    }

    #[test]
    fn clearing_a_site_never_touches_cache_targets() {
        // user:“站数据清理只清存储，缓存不动”+(这是口径断言：清理目标集合与缓存目标集合必须不相交)。
        let all = SiteDataKinds::all().targets();
        assert!(!all.is_empty());
        for target in &all {
            assert!(STORAGE_TARGETS.contains(target), "{target} 不在存储目标白名单里");
            assert!(!CACHE_TARGETS.contains(target), "{target} 属于缓存目标，不该出现在清理请求里");
            assert!(*target != "cache", "cache 不该出现在清理请求里");
        }
        assert!(all.contains(&"cookies"));
        assert!(all.contains(&"local_storage") && all.contains(&"indexed_db") && all.contains(&"service_worker"));
        assert!(!all.contains(&"disk_cache") && !all.contains(&"cache_storage"));
        // 只选 Cookie 时就只有 Cookie
        assert_eq!(SiteDataKinds::parse(Some(&["cookies".to_string()])).unwrap().targets(), vec!["cookies"]);
        // 缓存类目标被明确拒绝，而不是被静默忽略
        for cache in ["cache", "disk_cache", "cache_storage"] {
            let error = SiteDataKinds::parse(Some(&[cache.to_string()])).unwrap_err();
            assert_eq!(error.code, "unsupported", "{cache}");
            assert!(error.message.contains("不清理缓存"), "{cache}");
        }
    }

    #[test]
    fn host_normalization_strips_protocol_port_and_dots() {
        for (raw, expected) in [
            ("https://Example.COM/login?x=1", "example.com"),
            ("example.com:8443", "example.com"),
            ("http://example.com./a", "example.com"),
            ("user:pass@mail.example.com/x", "mail.example.com"),
            ("  localhost:5173  ", "localhost"),
            ("127.0.0.1", "127.0.0.1"),
        ] {
            assert_eq!(normalize_host(raw).as_deref(), Some(expected), "{raw}");
        }
        for bad in ["", "   ", "https://", "a b.com"] {
            assert_eq!(normalize_host(bad), None, "{bad}");
        }
        // 「带路径的裸 host」按 URL 语义切开：`exa/mple.com` 的 host 就是 `exa`，路径部分不属于 host。
        assert_eq!(normalize_host("exa/mple.com").as_deref(), Some("exa"));
        assert_eq!(require_host("").unwrap_err().code, "invalid_url");
    }

    #[test]
    fn cookie_domain_matching_covers_exact_parent_and_child() {
        // 完全一致
        assert!(cookie_domain_matches("example.com", "example.com"));
        assert!(cookie_domain_matches(".example.com", "example.com"));
        // 父域 cookie 作用于当前 host
        assert!(cookie_domain_matches(".example.com", "www.example.com"));
        // 当前 host 下的子域 cookie 一起清
        assert!(cookie_domain_matches("mail.example.com", "example.com"));
        // 不相关
        assert!(!cookie_domain_matches("example.com", "example.org"));
        assert!(!cookie_domain_matches("evilexample.com", "example.com"));
        assert!(!cookie_domain_matches("", "example.com"));
    }

    #[test]
    fn cookie_sources_cover_secure_and_plain() {
        assert_eq!(cookie_sources("example.com"), vec!["https://example.com/", "http://example.com/"]);
    }
}
