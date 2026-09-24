//! `web_fetch` for hosts without the Python tool stack.
//!
//! Fetches one URL and returns readable text. The desktop tool hands the raw
//! body to the model; this host additionally strips HTML tags, because a phone
//! conversation cannot afford a page of markup. Approval is required, matching
//! the desktop host: fetching an arbitrary URL is a network action the user
//! should see.
use crate::{
    DeviceCapabilities, RuntimeError, ToolCall, ToolDefinition, ToolPermission, ToolRuntime,
};
use async_trait::async_trait;
use regex_lite::Regex;
use serde_json::{json, Value};
use std::time::Duration;

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_BYTES: usize = 512 * 1024;
const MAX_TEXT_CHARS: usize = 20_000;
const MAX_REDIRECTS: usize = 5;

pub struct WebFetchTools {
    timeout: Duration,
}

impl Default for WebFetchTools {
    fn default() -> Self {
        Self {
            timeout: DEFAULT_TIMEOUT,
        }
    }
}

impl WebFetchTools {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }
}

/// Collapse an HTML document to readable text.
fn html_to_text(body: &str) -> String {
    // regex-lite has no backreferences, so each container is dropped by its own
    // pattern instead of one open/close expression.
    let mut without_containers = body.to_owned();
    for tag in ["script", "style", "noscript"] {
        let pattern = format!(r"(?is)<{tag}[^>]*>.*?</{tag}>");
        without_containers = Regex::new(&pattern)
            .expect("static container pattern")
            .replace_all(&without_containers, " ")
            .into_owned();
    }
    let with_breaks = Regex::new(r"(?i)</?(p|div|br|li|tr|h[1-6])[^>]*>")
        .expect("static block pattern")
        .replace_all(&without_containers, "\n");
    let text = Regex::new(r"<[^>]+>")
        .expect("static tag pattern")
        .replace_all(&with_breaks, "");
    decode_entities(&text)
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty())
        .collect::<Vec<_>>()
        .join("\n")
}

/// Decode the entities a fetched page commonly contains.
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
            _ => entity
                .strip_prefix('#')
                .and_then(|digits| match digits.strip_prefix(['x', 'X']) {
                    Some(hex) => u32::from_str_radix(hex, 16).ok(),
                    None => digits.parse::<u32>().ok(),
                })
                .and_then(char::from_u32),
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

#[async_trait]
impl ToolRuntime for WebFetchTools {
    fn definitions(&self, capabilities: &DeviceCapabilities) -> Vec<ToolDefinition> {
        if !capabilities.network {
            return Vec::new();
        }
        vec![ToolDefinition {
            name: "web_fetch".into(),
            description: "Fetch one http(s) URL and return its readable text. HTML is reduced to \
                          text; the result is truncated."
                .into(),
            input_schema: json!({
                "type": "object",
                "additionalProperties": false,
                "properties": {"url": {"type": "string", "description": "Absolute http(s) URL"}},
                "required": ["url"]
            }),
        }]
    }

    fn permission(&self, _call: &ToolCall) -> ToolPermission {
        ToolPermission::AskUser
    }

    async fn execute(&self, call: &ToolCall) -> Result<Value, RuntimeError> {
        let url = call
            .arguments
            .get("url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        if !url.starts_with("http://") && !url.starts_with("https://") {
            return Err(RuntimeError::Tool(
                "'url' must be an absolute http(s) URL".into(),
            ));
        }
        let client = reqwest::Client::builder()
            .timeout(self.timeout)
            .connect_timeout(Duration::from_secs(15))
            .redirect(reqwest::redirect::Policy::limited(MAX_REDIRECTS))
            .build()
            .map_err(|error| RuntimeError::Tool(error.to_string()))?;
        let response = client
            .get(&url)
            .send()
            .await
            .map_err(|error| {
                if error.is_timeout() {
                    RuntimeError::Tool("fetch timed out".into())
                } else {
                    RuntimeError::Tool(format!("fetch failed: {error}"))
                }
            })?;
        let status = response.status();
        if !status.is_success() {
            return Err(RuntimeError::Tool(format!(
                "fetch failed: HTTP {}",
                status.as_u16()
            )));
        }
        let content_type = response
            .headers()
            .get("content-type")
            .and_then(|value| value.to_str().ok())
            .unwrap_or_default()
            .to_ascii_lowercase();
        let body = response
            .bytes()
            .await
            .map_err(|error| RuntimeError::Tool(format!("read failed: {error}")))?;
        let truncated = body.len() > MAX_BYTES;
        let slice = &body[..body.len().min(MAX_BYTES)];
        let raw = String::from_utf8_lossy(slice).into_owned();
        let is_html = content_type.contains("html") || raw.trim_start().starts_with("<!DOCTYPE")
            || raw.trim_start().starts_with("<html");
        let text = if is_html { html_to_text(&raw) } else { raw };
        let clipped = text.chars().count() > MAX_TEXT_CHARS;
        let text = text.chars().take(MAX_TEXT_CHARS).collect::<String>();
        Ok(json!({
            "ok": true,
            "url": url,
            "content_type": content_type,
            "content": text,
            "truncated": truncated || clipped,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn html_is_reduced_to_readable_text() {
        let page = "<html><head><style>p{}</style><script>var x=1</script></head>\
                    <body><h1>Title</h1><p>One &amp; two</p><ul><li>Item</li></ul>\
                    <p>3 &lt; 5 &#39;quoted&#39; &#x4e2d;</p></body></html>";
        let text = html_to_text(page);
        assert!(text.contains("Title"));
        assert!(text.contains("One & two"));
        assert!(text.contains("Item"));
        assert!(text.contains("3 < 5 'quoted' 中"));
        // Script and style bodies never reach the model.
        assert!(!text.contains("var x=1"));
        assert!(!text.contains("p{}"));
        // Tags become lines, not run-on prose.
        assert!(text.lines().any(|line| line == "Title"));
    }

    #[test]
    fn the_tool_is_advertised_only_with_network_and_needs_approval() {
        let tools = WebFetchTools::new();
        assert!(tools.definitions(&DeviceCapabilities::default()).is_empty());
        let online = DeviceCapabilities {
            network: true,
            ..Default::default()
        };
        let definitions = tools.definitions(&online);
        assert_eq!(definitions.len(), 1);
        assert_eq!(definitions[0].name, "web_fetch");
        assert_eq!(definitions[0].input_schema["required"], json!(["url"]));
        assert_eq!(
            tools.permission(&ToolCall {
                id: "call".into(),
                name: "web_fetch".into(),
                arguments: json!({}),
            }),
            ToolPermission::AskUser
        );
    }

    #[tokio::test]
    async fn a_relative_url_is_rejected_before_any_request() {
        let tools = WebFetchTools::new();
        let error = tools
            .execute(&ToolCall {
                id: "call".into(),
                name: "web_fetch".into(),
                arguments: json!({"url": "example.com/page"}),
            })
            .await
            .expect_err("a non-absolute URL must be refused");
        assert!(error.to_string().contains("absolute http(s) URL"));
    }
}
