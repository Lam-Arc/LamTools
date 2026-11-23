// user:“内置浏览器、网页要能正常打开”+(外站是不可信输入：顶层导航只放行 http/https，地址栏输入要能区分网址与搜索词，规则只留一份)。
use crate::browser::BrowserError;
use serde::Serialize;

/// 默认搜索引擎：模板里的 `{query}` 会被百分号编码后的关键词替换。
pub const DEFAULT_SEARCH_NAME: &str = "Bing";
pub const DEFAULT_SEARCH_TEMPLATE: &str = "https://www.bing.com/search?q={query}";

/// 顶层导航明确拒绝的协议。`blob:` 只允许页面内部使用，不允许成为顶层文档。
pub const BLOCKED_SCHEMES: &[&str] = &[
    "javascript", "data", "file", "tauri", "asset", "ipc", "about", "blob", "chrome", "edge",
    "view-source", "vbscript", "mailto", "tel", "ftp", "ws", "wss",
];

// user:“地址栏里输入「天气」能搜到结果”+(搜索词走搜索引擎模板，不能被当成域名)。
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SearchEngine {
    pub name: String,
    pub template: String,
}

impl SearchEngine {
    pub fn default_engine() -> Self {
        Self { name: DEFAULT_SEARCH_NAME.to_string(), template: DEFAULT_SEARCH_TEMPLATE.to_string() }
    }

    pub fn url_for(&self, query: &str) -> Result<String, BrowserError> {
        let query = query.trim();
        if query.is_empty() {
            return Err(BrowserError::new("invalid_url", "请输入要搜索的内容", false));
        }
        let encoded = urlencoding::encode(query);
        let raw = self.template.replace("{query}", &encoded);
        let parsed = parse_web(&raw)?;
        Ok(parsed.to_string())
    }
}

impl Default for SearchEngine {
    fn default() -> Self {
        Self::default_engine()
    }
}

/// 地址栏输入的分类结果。
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AddressInput {
    Url(String),
    Search(String),
}

/// 顶层导航白名单：只有带主机的 http/https 可以成为文档。
pub fn allowed_navigation(url: &url::Url) -> bool {
    matches!(url.scheme(), "http" | "https") && url.host_str().map(|host| !host.is_empty()).unwrap_or(false)
}

pub fn parse_web(raw: &str) -> Result<url::Url, BrowserError> {
    let parsed = url::Url::parse(raw.trim())
        .map_err(|_| BrowserError::new("invalid_url", "请输入完整的网页地址", false))?;
    if !allowed_navigation(&parsed) {
        return Err(blocked_scheme(parsed.scheme()));
    }
    Ok(parsed)
}

pub fn blocked_scheme(scheme: &str) -> BrowserError {
    BrowserError::new("blocked_scheme", format!("不支持在浏览器里打开 {scheme}: 链接"), false)
}

/// 取显式写出的协议名。`localhost:3000` 这种 host:port 也会被这里切出一段，由调用方按端口判定。
fn explicit_scheme(raw: &str) -> Option<(&str, &str)> {
    let bytes = raw.as_bytes();
    if bytes.is_empty() || !bytes[0].is_ascii_alphabetic() {
        return None;
    }
    let mut index = 1;
    while index < bytes.len()
        && (bytes[index].is_ascii_alphanumeric() || matches!(bytes[index], b'+' | b'-' | b'.'))
    {
        index += 1;
    }
    if index < bytes.len() && bytes[index] == b':' {
        Some((&raw[..index], &raw[index + 1..]))
    } else {
        None
    }
}

fn host_of(text: &str) -> &str {
    let host = text.split(['/', '?', '#']).next().unwrap_or(text);
    match host.rsplit_once(':') {
        Some((name, port)) if !port.is_empty() && port.chars().all(|c| c.is_ascii_digit()) => name,
        _ => host,
    }
}

fn is_local_host(text: &str) -> bool {
    let host = text.split(['/', '?', '#']).next().unwrap_or(text);
    // IPv6 字面量在首版按本地地址处理（站点自测用），完整解析标为待验证。
    if host.starts_with('[') {
        return true;
    }
    let host = host_of(text);
    host.eq_ignore_ascii_case("localhost") || host.parse::<std::net::Ipv4Addr>().is_ok()
}

/// 像域名的判断只看主机的形状：不含空白、全 ASCII、带点，且最后一段是至少两位的字母（`v2.0` 走搜索）。
fn looks_like_domain(text: &str) -> bool {
    if text.is_empty() || text.chars().any(|c| c.is_whitespace()) || !text.is_ascii() {
        return false;
    }
    let host = host_of(text);
    if !host.contains('.') {
        return false;
    }
    match host.split('.').next_back() {
        Some(last) => last.len() >= 2 && last.chars().all(|c| c.is_ascii_alphabetic()),
        None => false,
    }
}

fn host_candidate(text: &str) -> String {
    let trimmed = text.trim_end_matches('/');
    let scheme = if is_local_host(trimmed) { "http" } else { "https" };
    if trimmed.contains('/') {
        format!("{scheme}://{trimmed}")
    } else {
        format!("{scheme}://{trimmed}/")
    }
}

// user:“地址栏输入网址、搜索、localhost 都要能用”+(同一个输入先按网址试，试不成才当搜索词)。
pub fn resolve_address(raw: &str, engine: &SearchEngine) -> Result<AddressInput, BrowserError> {
    let text = raw.trim();
    if text.is_empty() {
        return Err(BrowserError::new("invalid_url", "请输入网址或搜索内容", false));
    }
    if let Some((scheme, rest)) = explicit_scheme(text) {
        let lower = scheme.to_ascii_lowercase();
        // `localhost:3000`、`example.com:8080` 里冒号后面是端口，不是协议。
        let port_like = !rest.starts_with("//")
            && !rest.is_empty()
            && rest.chars().all(|c| c.is_ascii_digit());
        if !port_like {
            if lower == "http" || lower == "https" {
                return Ok(AddressInput::Url(parse_web(text)?.to_string()));
            }
            return Err(blocked_scheme(&lower));
        }
    }
    if is_local_host(text) || looks_like_domain(text) {
        if let Ok(parsed) = parse_web(&host_candidate(text)) {
            return Ok(AddressInput::Url(parsed.to_string()));
        }
    }
    Ok(AddressInput::Search(engine.url_for(text)?))
}

/// 导航目标：显式地址优先，其次搜索。返回的一定是可以交给 webview 的 http/https 地址。
pub fn navigation_target(raw: &str, engine: &SearchEngine) -> Result<url::Url, BrowserError> {
    match resolve_address(raw, engine)? {
        AddressInput::Url(url) | AddressInput::Search(url) => parse_web(&url),
    }
}

pub fn require_main(view: &tauri::Webview) -> Result<(), BrowserError> {
    // user:“只有主窗口能发命令”+(子 webview 加载的是不可信网页，不能反向指挥宿主)。
    if view.label() == "main" {
        Ok(())
    } else {
        Err(BrowserError::new("permission_denied", "此操作仅供主工作区使用", false))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn engine() -> SearchEngine {
        SearchEngine::default_engine()
    }

    fn kind(raw: &str) -> Result<AddressInput, BrowserError> {
        resolve_address(raw, &engine())
    }

    #[test]
    fn accepts_web_addresses() {
        for raw in [
            "https://example.com/docs",
            "http://example.com",
            "example.com",
            "example.com/path?q=1",
        ] {
            match kind(raw).unwrap() {
                AddressInput::Url(url) => assert!(url.starts_with("http"), "{raw} -> {url}"),
                AddressInput::Search(_) => panic!("{raw} 应该被识别成网址"),
            }
        }
    }

    #[test]
    fn local_hosts_use_plain_http() {
        for (raw, expected) in [
            ("localhost", "http://localhost/"),
            ("localhost:3000", "http://localhost:3000/"),
            ("127.0.0.1:5173", "http://127.0.0.1:5173/"),
            ("192.168.1.1", "http://192.168.1.1/"),
        ] {
            match kind(raw).unwrap() {
                AddressInput::Url(url) => assert_eq!(url, expected),
                AddressInput::Search(_) => panic!("{raw} 应该被识别成网址"),
            }
        }
    }

    #[test]
    fn keywords_become_search_queries() {
        for raw in ["天气", "好用的 网站", "rust cargo", "hello"] {
            match kind(raw).unwrap() {
                AddressInput::Search(url) => {
                    assert!(url.starts_with("https://"), "{raw} -> {url}");
                    assert!(!url.contains(' '), "搜索词必须编码");
                }
                AddressInput::Url(url) => panic!("{raw} 应该走搜索，实际是 {url}"),
            }
        }
    }

    #[test]
    fn search_query_is_percent_encoded() {
        let url = engine().url_for("a b&c").unwrap();
        assert!(url.contains("a%20b%26c"), "{url}");
    }

    #[test]
    fn rejects_dangerous_schemes() {
        for raw in [
            "file:///C:/Windows",
            "javascript:alert(1)",
            "data:text/html,x",
            "tauri://localhost",
            "asset://localhost/x.png",
            "about:blank",
            "blob:https://example.com/uuid",
            "mailto:someone@example.com",
            "ipc://localhost/x",
            "ws://example.com/socket",
        ] {
            let error = kind(raw).expect_err(raw);
            assert_eq!(error.code, "blocked_scheme", "{raw} -> {error:?}");
        }
    }

    #[test]
    fn rejects_malformed_web_addresses() {
        for raw in ["https://", "http://", "https://?q=1"] {
            let error = kind(raw).expect_err(raw);
            assert!(matches!(error.code.as_str(), "invalid_url" | "blocked_scheme"), "{raw} -> {error:?}");
        }
    }

    #[test]
    fn navigation_target_is_always_web() {
        for raw in ["example.com", "天气", "localhost:8080"] {
            let url = navigation_target(raw, &engine()).unwrap();
            assert!(allowed_navigation(&url), "{raw} -> {url}");
        }
    }
}
