//! Web search tool for hosts without the Python search stack.
//!
//! The desktop host discovers `web_search` from the bundled websearch plugin and
//! runs it through three in-process Python kernels. The mobile host has no
//! Python, so this module ports those kernels with the same query shaping,
//! result shape, provider order and failure semantics — a search that behaved
//! differently per platform would be worse than not having one.
//!
//! Image search stays desktop-only: the Python side needs the image-candidate
//! extractor, and the tool schema here advertises `web` only rather than
//! offering a mode that would always fail.
use crate::{
    DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition, ToolPermission, ToolRuntime,
};
use async_trait::async_trait;
use base64::Engine;
use regex_lite::Regex;
use serde_json::{json, Value};
use std::time::Duration;

const DEFAULT_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
                          (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";
const MAX_RESULT_COUNT: usize = 20;
const DEFAULT_LIMIT: usize = 5;
/// Search order used when the caller does not name a kernel. `ddg` is blocked on
/// mainland networks, which is why the chain falls through to `baidu` and `bing`.
const DEFAULT_FALLBACK_PROVIDERS: [&str; 3] = ["ddg", "baidu", "bing"];
/// Kernels this host implements. The desktop schema lists the same three plus a
/// `custom` option that needs a Python-side adapter, so it is not accepted here.
const KNOWN_PROVIDERS: [&str; 3] = ["ddg", "baidu", "bing"];

const DDG_ENDPOINT: &str = "https://html.duckduckgo.com/html/";
const BAIDU_ENDPOINT: &str = "https://www.baidu.com/s";
const BAIDU_RESULTS_PER_PAGE: usize = 10;
const BING_ENDPOINT: &str = "https://cn.bing.com/search";
const BING_MARKET: &str = "zh-CN";

/// One result in the shared kernel output shape.
#[derive(Clone, Debug, PartialEq, Eq)]
struct SearchResult {
    title: String,
    url: String,
    snippet: String,
    source: &'static str,
}

fn client(timeout_secs: u64, follow_redirects: bool) -> Result<reqwest::Client, RuntimeError> {
    let policy = if follow_redirects {
        reqwest::redirect::Policy::limited(10)
    } else {
        // Baidu answers with a redirect to its captcha page; seeing the status
        // is what lets the caller report the real reason.
        reqwest::redirect::Policy::none()
    };
    reqwest::Client::builder()
        .timeout(Duration::from_secs(timeout_secs))
        .user_agent(DEFAULT_UA)
        .redirect(policy)
        .build()
        .map_err(|error| RuntimeError::Tool(error.to_string()))
}

/// Percent-encode one value for application/x-www-form-urlencoded or a query
/// string. `reqwest`'s `form`/`query` helpers need a feature that the shared
/// runtime does not enable, and the encoding here is small enough to test.
fn encode_component(value: &str, space_as_plus: bool) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.as_bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(*byte as char)
            }
            b' ' if space_as_plus => out.push('+'),
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

fn form_body(pairs: &[(&str, String)]) -> String {
    pairs
        .iter()
        .map(|(key, value)| format!("{}={}", encode_component(key, true), encode_component(value, true)))
        .collect::<Vec<_>>()
        .join("&")
}

fn query_url(endpoint: &str, pairs: &[(&str, String)]) -> String {
    let query = pairs
        .iter()
        .map(|(key, value)| {
            format!(
                "{}={}",
                encode_component(key, false),
                encode_component(value, false)
            )
        })
        .collect::<Vec<_>>()
        .join("&");
    format!("{endpoint}?{query}")
}

/// `site:` filters are appended to the query, matching the Python kernels.
fn query_with_domains(query: &str, domains: &[String]) -> String {
    if domains.is_empty() {
        return query.to_owned();
    }
    let filters = domains
        .iter()
        .map(|domain| format!("site:{domain}"))
        .collect::<Vec<_>>()
        .join(" ");
    format!("{query} {filters}")
}

/// Drop tags and decode the entities the kernels can produce.
///
/// The Python kernels strip tags and then `unescape()` the text, so a numeric
/// entity survives the first pass and is decoded by the second; doing both here
/// keeps a single decoding step without changing the result.
fn clean_html(raw: &str) -> String {
    let without_tags = Regex::new(r"<[^>]+>")
        .expect("static tag pattern")
        .replace_all(raw, "")
        .trim()
        .to_owned();
    decode_entities(&without_tags)
}

fn decode_entities(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    let mut rest = value;
    while let Some(index) = rest.find('&') {
        out.push_str(&rest[..index]);
        rest = &rest[index..];
        let Some(end) = rest.find(';').filter(|end| *end <= 10) else {
            out.push('&');
            rest = &rest[1..];
            continue;
        };
        let entity = &rest[1..end];
        let decoded = match entity {
            "amp" => Some('&'),
            "lt" => Some('<'),
            "gt" => Some('>'),
            "quot" => Some('"'),
            "apos" | "#39" => Some('\''),
            "nbsp" => Some(' '),
            _ => numeric_entity(entity),
        };
        match decoded {
            Some(character) => {
                out.push(character);
                rest = &rest[end + 1..];
            }
            None => {
                out.push('&');
                rest = &rest[1..];
            }
        }
    }
    out.push_str(rest);
    out
}

fn numeric_entity(entity: &str) -> Option<char> {
    let digits = entity.strip_prefix('#')?;
    let code = match digits.strip_prefix(['x', 'X']) {
        Some(hex) => u32::from_str_radix(hex, 16).ok()?,
        None => digits.parse::<u32>().ok()?,
    };
    char::from_u32(code)
}

async fn search_ddg(
    timeout_secs: u64,
    query: &str,
    limit: usize,
    domains: &[String],
) -> Result<Vec<SearchResult>, String> {
    let http = client(timeout_secs, true).map_err(|error| error.to_string())?;
    let response = http
        .post(DDG_ENDPOINT)
        .header("content-type", "application/x-www-form-urlencoded")
        .body(form_body(&[("q", query_with_domains(query, domains))]))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    if response.status().as_u16() != 200 {
        return Err(format!("DuckDuckGo 返回 HTTP {}", response.status().as_u16()));
    }
    let text = response.text().await.map_err(|error| error.to_string())?;
    let link = Regex::new(r#"<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>"#)
        .expect("static ddg link pattern");
    let snippet = Regex::new(r#"<a[^>]*class="result__snippet"[^>]*>(.*?)</a>"#)
        .expect("static ddg snippet pattern");
    let links = link.captures_iter(&text).collect::<Vec<_>>();
    let snippets = snippet
        .captures_iter(&text)
        .map(|capture| clean_html(&capture[1]))
        .collect::<Vec<_>>();
    let mut results = Vec::new();
    for (index, capture) in links.into_iter().take(limit).enumerate() {
        let url = capture[1].trim().to_owned();
        let title = clean_html(&capture[2]);
        if title.is_empty() || url.is_empty() {
            continue;
        }
        results.push(SearchResult {
            title,
            url,
            snippet: snippets.get(index).cloned().unwrap_or_default(),
            source: "ddg",
        });
    }
    Ok(results)
}

fn random_hex(bytes: usize) -> String {
    let seed = uuid::Uuid::new_v4().simple().to_string();
    seed.chars().take(bytes * 2).collect()
}

async fn search_baidu_once(
    timeout_secs: u64,
    query: &str,
    limit: usize,
    domains: &[String],
) -> Result<Vec<SearchResult>, String> {
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_millis().to_string())
        .unwrap_or_default();
    let http = client(timeout_secs, false).map_err(|error| error.to_string())?;
    let response = http
        .get(query_url(
            BAIDU_ENDPOINT,
            &[
                ("wd", query_with_domains(query, domains)),
                ("rn", BAIDU_RESULTS_PER_PAGE.to_string()),
                ("pn", "0".to_owned()),
                ("tn", "json".to_owned()),
                // The Python kernel sends browser-ish params by default; Baidu
                // treats their absence as a scraper signal.
                ("rsv_pq", random_hex(16)),
                ("rsv_t", now_ms),
                ("oq", query.to_owned()),
            ],
        ))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    let status = response.status().as_u16();
    if (300..=308).contains(&status) {
        let location = response
            .headers()
            .get("location")
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_owned();
        if location.contains("wappass") || location.contains("captcha") {
            return Err("百度安全验证（wappass captcha），请稍后重试或更换内核".into());
        }
        return Err(format!("百度重定向（HTTP {status}），可能被反爬拦截"));
    }
    if status != 200 {
        return Err(format!("百度返回 HTTP {status}"));
    }
    let text = response.text().await.map_err(|error| error.to_string())?;
    let Ok(data) = serde_json::from_str::<Value>(&text) else {
        return Err("百度返回非 JSON（可能被反爬拦截）".into());
    };
    let anti_flag = data.get("antiFlag");
    if anti_flag == Some(&json!(1)) || anti_flag == Some(&json!("1")) {
        return Err("百度拒绝爬虫访问（antiFlag==1）".into());
    }
    let entries = data
        .pointer("/feed/entry")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut results = Vec::new();
    for entry in entries.into_iter().take(limit) {
        let title = decode_entities(
            entry
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .trim(),
        );
        let url = entry
            .get("url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if title.is_empty() || url.is_empty() {
            continue;
        }
        results.push(SearchResult {
            title,
            url,
            snippet: decode_entities(
                entry
                    .get("abs")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim(),
            ),
            source: "baidu",
        });
    }
    Ok(results)
}

/// Baidu occasionally serves an anti-scraping page; the Python kernel retries
/// twice with a short backoff, and so does this one.
async fn search_baidu(
    timeout_secs: u64,
    query: &str,
    limit: usize,
    domains: &[String],
) -> Result<Vec<SearchResult>, String> {
    let mut last = String::new();
    for attempt in 0..3u64 {
        match search_baidu_once(timeout_secs, query, limit, domains).await {
            Ok(results) => return Ok(results),
            Err(error) => {
                last = error;
                if attempt < 2 {
                    tokio::time::sleep(Duration::from_millis(1000 + attempt * 1000)).await;
                }
            }
        }
    }
    Err(last)
}

/// Bing wraps results in a `/ck/a` redirect whose target is base64url encoded.
fn decode_bing_redirect(href: &str) -> String {
    const PREFIX: &str = "https://www.bing.com/ck/a";
    if !href.starts_with(PREFIX) {
        return href.to_owned();
    }
    let Some(query) = href.split_once('?').map(|(_, query)| query) else {
        return href.to_owned();
    };
    let Some(value) = query.split('&').find_map(|pair| {
        let (key, value) = pair.split_once('=')?;
        (key == "u").then_some(value)
    }) else {
        return href.to_owned();
    };
    let Some(encoded) = value.strip_prefix("a1") else {
        return href.to_owned();
    };
    match base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(encoded) {
        Ok(bytes) => String::from_utf8_lossy(&bytes).into_owned(),
        Err(_) => href.to_owned(),
    }
}

/// Query tokens used by the relevance sanity check below.
fn query_tokens(query: &str) -> Vec<&str> {
    query
        .split(|character: char| {
            character.is_whitespace() || "-—/·,，。.".contains(character)
        })
        .filter(|token| token.chars().count() >= 2)
        .collect()
}

async fn search_bing(
    timeout_secs: u64,
    query: &str,
    limit: usize,
    domains: &[String],
) -> Result<Vec<SearchResult>, String> {
    let http = client(timeout_secs, true).map_err(|error| error.to_string())?;
    let response = http
        .get(query_url(
            BING_ENDPOINT,
            &[
                ("q", query_with_domains(query, domains)),
                ("mkt", BING_MARKET.to_owned()),
                ("setlang", "zh-hans".to_owned()),
            ],
        ))
        .send()
        .await
        .map_err(|error| error.to_string())?;
    let status = response.status().as_u16();
    if status != 200 {
        return Err(format!("Bing 返回 HTTP {status}"));
    }
    let text = response.text().await.map_err(|error| error.to_string())?;
    if !text.contains("b_results") && !text.contains("b_algo") {
        let lowered = text.to_lowercase();
        if ["captcha", "challenge", "verify"]
            .iter()
            .any(|marker| lowered.contains(marker))
        {
            return Err("Bing 触发验证码/挑战".into());
        }
        return Err("Bing 响应中未找到结果结构（可能被反爬）".into());
    }
    let item = Regex::new(
        r#"<li class="b_algo"[^>]*>.*?<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</li>"#,
    )
    .expect("static bing item pattern");
    let block = Regex::new(r#"<li class="b_algo"[^>]*>(.*?)</li>"#).expect("static bing block");
    let paragraph = Regex::new(r"<p[^>]*>(.*?)</p>").expect("static bing paragraph");

    let mut results = item
        .captures_iter(&text)
        .take(limit)
        .filter_map(|capture| {
            let title = clean_html(&capture[2]);
            let url = decode_bing_redirect(capture[1].trim());
            if title.is_empty() || url.is_empty() {
                return None;
            }
            Some(SearchResult {
                title,
                url,
                snippet: String::new(),
                source: "bing",
            })
        })
        .collect::<Vec<_>>();

    // Snippets come from the first paragraph inside each result block.
    let blocks = block.captures_iter(&text).collect::<Vec<_>>();
    for (index, capture) in blocks.into_iter().take(limit).enumerate() {
        if index >= results.len() {
            break;
        }
        if let Some(paragraph) = paragraph.captures(&capture[1]) {
            results[index].snippet = decode_entities(
                &paragraph[1].replace("<span class=\"algoSlug_icon\">", ""),
            )
            .trim()
            .to_owned();
        }
    }

    // Bing's Chinese segmentation is unreliable; the Python kernel refuses a
    // result set whose first title shares no token with the query instead of
    // returning unrelated results, and the fallback chain relies on that.
    if let Some(first) = results.first() {
        let tokens = query_tokens(query);
        if tokens.len() >= 2 && !tokens.iter().any(|token| first.title.contains(token)) {
            let preview = first.title.chars().take(20).collect::<String>();
            return Err(format!(
                "Bing 中文分词异常：查询 {query:?} 被误判（首条结果 '{preview}...' 与查询无公共词元），请换用 baidu 内核或调整措辞"
            ));
        }
    }
    Ok(results)
}

async fn run_provider(
    provider: &str,
    timeout_secs: u64,
    query: &str,
    limit: usize,
    domains: &[String],
) -> Result<Vec<SearchResult>, String> {
    match provider {
        "ddg" => search_ddg(timeout_secs, query, limit, domains).await,
        "baidu" => search_baidu(timeout_secs, query, limit, domains).await,
        "bing" => search_bing(timeout_secs, query, limit, domains).await,
        other => Err(format!("未知搜索内核: {other}")),
    }
}

/// The desktop `web_search` tool, backed by the ported kernels.
pub struct WebSearchTools {
    /// Caller-chosen kernel, or empty to use [`Self::fallback`] in order.
    provider: String,
    fallback: Vec<String>,
    limit: usize,
    timeout_secs: u64,
}

impl Default for WebSearchTools {
    fn default() -> Self {
        Self {
            provider: String::new(),
            fallback: DEFAULT_FALLBACK_PROVIDERS
                .iter()
                .map(|name| (*name).to_owned())
                .collect(),
            limit: DEFAULT_LIMIT,
            timeout_secs: 30,
        }
    }
}

impl WebSearchTools {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_timeout_secs(mut self, timeout_secs: u64) -> Self {
        self.timeout_secs = timeout_secs.max(1);
        self
    }

    /// Apply the bundled websearch plugin's settings.
    ///
    /// The desktop reads them from the plugin's `config/schema.jsonc`
    /// (provider, limit, timeout, fallback order); the host resolves the values
    /// and hands them over, so the kernel chosen in the panel is the one that
    /// runs. Unknown kernels and out-of-range numbers fall back to the defaults
    /// rather than leaving search unusable.
    pub fn with_config(
        mut self,
        provider: &str,
        fallback: &[String],
        limit: Option<u64>,
        timeout_secs: Option<u64>,
    ) -> Self {
        let provider = provider.trim().to_lowercase();
        self.provider = if KNOWN_PROVIDERS.contains(&provider.as_str()) {
            provider
        } else {
            String::new()
        };
        let fallback: Vec<String> = fallback
            .iter()
            .map(|name| name.trim().to_lowercase())
            .filter(|name| KNOWN_PROVIDERS.contains(&name.as_str()))
            .collect();
        if !fallback.is_empty() {
            self.fallback = fallback;
        }
        if let Some(limit) = limit {
            self.limit = (limit as usize).clamp(1, MAX_RESULT_COUNT);
        }
        if let Some(timeout_secs) = timeout_secs {
            self.timeout_secs = timeout_secs.max(1);
        }
        self
    }

    /// Effective configuration, for hosts that report what is in force.
    pub fn limit(&self) -> usize {
        self.limit
    }

    pub fn timeout_secs(&self) -> u64 {
        self.timeout_secs
    }

    /// Kernel order for one call: an explicit per-call override wins, otherwise
    /// the configured provider runs first and the configured chain follows —
    /// the same order the Python host builds.
    fn provider_order(&self, requested: &str) -> Result<Vec<String>, RuntimeError> {
        let requested = requested.trim().to_lowercase();
        if !requested.is_empty() {
            if !KNOWN_PROVIDERS.contains(&requested.as_str()) {
                return Err(RuntimeError::Tool(format!(
                    "未知搜索内核: {requested}（可选: ddg/baidu/bing）"
                )));
            }
            return Ok(vec![requested]);
        }
        let mut candidates: Vec<String> = Vec::new();
        if !self.provider.is_empty() {
            candidates.push(self.provider.clone());
        }
        for name in &self.fallback {
            if !candidates.iter().any(|existing| existing == name) {
                candidates.push(name.clone());
            }
        }
        // Nothing configured must still search: fall back to the default chain.
        Ok(if candidates.is_empty() {
            DEFAULT_FALLBACK_PROVIDERS
                .iter()
                .map(|name| (*name).to_owned())
                .collect()
        } else {
            candidates
        })
    }
}

#[async_trait]
impl ToolRuntime for WebSearchTools {
    fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        if !capabilities.network {
            return Vec::new();
        }
        vec![ToolDefinition {
            name: "web_search".into(),
            description: "Search web pages. Returns titles, URLs and snippets from the \
                          configured search kernels."
                .into(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Precise search query."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum result count"
                    },
                    "domains": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Domain filter"
                    },
                    "search_type": {
                        "type": "string",
                        "description": "Only 'web' is available on this host.",
                        "enum": ["web"]
                    },
                    "provider": {
                        "type": "string",
                        "description": "Optional search kernel override",
                        "enum": ["ddg", "baidu", "bing"]
                    }
                },
                "required": ["query"]
            }),
        }]
    }

    fn permission(&self, _call: &ToolCall) -> ToolPermission {
        ToolPermission::AutoAllow
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        let arguments = call.arguments.as_object();
        let query = arguments
            .and_then(|map| map.get("query"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if query.is_empty() {
            return Err(RuntimeError::Tool("Missing 'query' argument".into()));
        }
        let search_type = arguments
            .and_then(|map| map.get("search_type"))
            .and_then(Value::as_str)
            .unwrap_or("web")
            .trim()
            .to_lowercase();
        if search_type != "web" {
            return Err(RuntimeError::Tool(format!(
                "search_type '{search_type}' is not available on this host; only 'web' is supported"
            )));
        }
        let limit = arguments
            .and_then(|map| map.get("limit"))
            .and_then(Value::as_u64)
            .map(|value| value as usize)
            .unwrap_or(self.limit)
            .clamp(1, MAX_RESULT_COUNT);
        let domains = arguments
            .and_then(|map| map.get("domains"))
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(str::trim)
                    .filter(|domain| !domain.is_empty())
                    .map(str::to_owned)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let requested = arguments
            .and_then(|map| map.get("provider"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_lowercase();

        let providers = self.provider_order(&requested)?;

        let mut errors: Vec<String> = Vec::new();
        let mut attempted: Vec<&str> = Vec::new();
        let mut results: Vec<SearchResult> = Vec::new();
        let mut used = providers[0].as_str();
        for provider in &providers {
            attempted.push(provider);
            match run_provider(provider, self.timeout_secs, &query, limit, &domains).await {
                Ok(found) => {
                    used = provider;
                    if !found.is_empty() {
                        results = found;
                        break;
                    }
                }
                Err(error) => errors.push(format!("{provider}: {error}")),
            }
        }

        if results.is_empty() && !errors.is_empty() && errors.len() == attempted.len() {
            return Err(RuntimeError::Tool(format!(
                "web_search failed ({})",
                errors.join("; ")
            )));
        }
        if results.is_empty() {
            return Ok(json!({
                "ok": true,
                "content": format!("[web_search] No results found for query: {query}"),
                "query": query,
                "provider": used,
                "result_count": 0,
                "results": [],
            }));
        }

        let lines = results
            .iter()
            .enumerate()
            .map(|(index, result)| {
                format!(
                    "{}. {}\n   URL: {}\n   {}",
                    index + 1,
                    result.title,
                    result.url,
                    result.snippet
                )
            })
            .collect::<Vec<_>>()
            .join("\n\n");
        Ok(json!({
            "ok": true,
            "content": format!("[web_search results for '{query}']\n\n{lines}"),
            "query": query,
            "provider": used,
            "result_count": results.len(),
            "results": results
                .iter()
                .map(|result| json!({
                    "title": result.title,
                    "url": result.url,
                    "snippet": result.snippet,
                    "source": result.source,
                }))
                .collect::<Vec<_>>(),
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configured_kernels_decide_what_runs() {
        // The panel's provider choice runs first, followed by the default chain
        // (Python builds `[provider] + fallback_providers`, deduplicated).
        let tools = WebSearchTools::new().with_config("bing", &[], None, None);
        assert_eq!(
            tools.provider_order("").unwrap(),
            vec!["bing".to_owned(), "ddg".to_owned(), "baidu".to_owned()]
        );
        // ... a per-call override still wins ...
        assert_eq!(tools.provider_order("baidu").unwrap(), vec!["baidu".to_owned()]);
        // ... and an unknown kernel is refused, like the Python host refuses it.
        assert!(tools.provider_order("google").is_err());

        // An empty configuration falls back to the documented chain.
        let bare = WebSearchTools::new();
        assert_eq!(
            bare.provider_order("").unwrap(),
            vec!["ddg".to_owned(), "baidu".to_owned(), "bing".to_owned()]
        );

        // Configured values are normalised, unknown fallbacks are dropped, and
        // the chain keeps the configured provider first (Python's order).
        let normalised = WebSearchTools::new().with_config(
            "BING",
            &["baidu".into(), "GOOGLE".into(), " ".into(), "bing".into()],
            Some(999),
            Some(0),
        );
        assert_eq!(
            normalised.provider_order("").unwrap(),
            vec!["bing".to_owned(), "baidu".to_owned()]
        );
        assert_eq!(normalised.limit, MAX_RESULT_COUNT);
        assert_eq!(normalised.timeout_secs, 1);
        let ignored = WebSearchTools::new().with_config("", &["nope".into()], None, None);
        assert_eq!(
            ignored.provider_order("").unwrap(),
            vec!["ddg".to_owned(), "baidu".to_owned(), "bing".to_owned()]
        );
    }

    #[test]
    fn domain_filters_match_the_python_query_shaping() {
        assert_eq!(query_with_domains("rust async", &[]), "rust async");
        assert_eq!(
            query_with_domains("rust async", &["doc.rust-lang.org".into(), "tokio.rs".into()]),
            "rust async site:doc.rust-lang.org site:tokio.rs"
        );
    }

    #[test]
    fn cleaning_strips_tags_and_decodes_named_and_numeric_entities() {
        assert_eq!(clean_html("<b>Rust</b> &amp; C&lt;x&gt;"), "Rust & C<x>");
        assert_eq!(clean_html("a&nbsp;b"), "a b");
        assert_eq!(clean_html("&#39;quoted&#39;"), "'quoted'");
        assert_eq!(clean_html("&#x4e2d;"), "中");
        // A bare ampersand is data, not a broken entity.
        assert_eq!(clean_html("Tom & Jerry"), "Tom & Jerry");
    }

    #[test]
    fn bing_redirects_decode_to_their_target() {
        // "a1" + base64url("https://example.com/x")
        let encoded = base64::engine::general_purpose::URL_SAFE_NO_PAD
            .encode("https://example.com/x");
        let href = format!("https://www.bing.com/ck/a?u=a1{encoded}&ntb=1");
        assert_eq!(decode_bing_redirect(&href), "https://example.com/x");
        assert_eq!(
            decode_bing_redirect("https://example.com/direct"),
            "https://example.com/direct"
        );
    }

    #[test]
    fn query_tokens_mirror_the_python_split() {
        assert_eq!(query_tokens("rust-async 编程"), vec!["rust", "async", "编程"]);
        // Single-character tokens are dropped, and so is punctuation.
        assert_eq!(query_tokens("a，b"), Vec::<&str>::new());
    }

    #[test]
    fn tool_is_advertised_only_where_the_network_exists() {
        let tools = WebSearchTools::new();
        let offline = DeviceCapabilities::default();
        assert!(tools.definitions(&offline).is_empty());
        let online = DeviceCapabilities {
            network: true,
            ..Default::default()
        };
        let schema = &tools.definitions(&online)[0].input_schema;
        assert_eq!(tools.definitions(&online)[0].name, "web_search");
        // Image search is desktop-only, so it must not be advertised here.
        assert_eq!(schema["properties"]["search_type"]["enum"], json!(["web"]));
        assert_eq!(schema["required"], json!(["query"]));
    }

    #[tokio::test]
    async fn a_missing_query_is_rejected_before_any_request() {
        let tools = WebSearchTools::new();
        let error = tools
            .execute(&ToolCall {
                id: "call-1".into(),
                name: "web_search".into(),
                arguments: json!({}),
            })
            .await
            .expect_err("empty query must fail");
        assert!(error.to_string().contains("Missing 'query' argument"));
    }

    #[tokio::test]
    async fn an_unsupported_search_type_fails_loudly_instead_of_searching_web() {
        let tools = WebSearchTools::new();
        let error = tools
            .execute(&ToolCall {
                id: "call-1".into(),
                name: "web_search".into(),
                arguments: json!({"query": "rust", "search_type": "image"}),
            })
            .await
            .expect_err("image search is not available");
        assert!(error.to_string().contains("only 'web' is supported"));
    }

    #[tokio::test]
    async fn an_unknown_kernel_lists_the_supported_ones() {
        let tools = WebSearchTools::new();
        let error = tools
            .execute(&ToolCall {
                id: "call-1".into(),
                name: "web_search".into(),
                arguments: json!({"query": "rust", "provider": "searx"}),
            })
            .await
            .expect_err("unknown kernel must fail");
        assert!(error.to_string().contains("ddg/baidu/bing"));
    }
}
