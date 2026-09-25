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
/// Desktop `tool/web_tools.py`: `clean[:30000]` for the model-visible text, and
/// `normalize_pdf_bytes(..., max_text_length=30_000)` for PDFs.
const MAX_TEXT_CHARS: usize = 30_000;
/// Desktop fetches with `follow_redirects=True`, which is httpx's default of 20.
const MAX_REDIRECTS: usize = 20;

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
        // The desktop reads the whole body and truncates the model-visible text
        // afterwards; a byte cap here would silently cut a page the desktop
        // would have delivered in full.
        let raw = String::from_utf8_lossy(&body).into_owned();
        let is_html = content_type.contains("html") || raw.trim_start().starts_with("<!DOCTYPE")
            || raw.trim_start().starts_with("<html");
        let text = if is_html { html_to_text(&raw) } else { raw };
        let total_chars = text.chars().count();
        let clipped = total_chars > MAX_TEXT_CHARS;
        let text = if clipped {
            // Same marker the desktop appends (`tool/web_tools.py`), so the model
            // reads the same sentence on either host.
            format!(
                "{}\n\n[... truncated at {MAX_TEXT_CHARS} / {total_chars} chars]",
                text.chars().take(MAX_TEXT_CHARS).collect::<String>()
            )
        } else {
            text
        };
        Ok(json!({
            "ok": true,
            "url": url,
            "content_type": content_type,
            "content": text,
            "truncated": clipped,
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

    /// Serve one canned response per connection, then keep the socket open until
    /// the test ends. Returns the base URL.
    fn serve<F>(handler: F) -> String
    where
        F: Fn(&str) -> String + Send + Sync + 'static,
    {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                let mut buffer = [0u8; 4096];
                let read = stream.read(&mut buffer).unwrap_or(0);
                let request = String::from_utf8_lossy(&buffer[..read]).to_string();
                let path = request.split_whitespace().nth(1).unwrap_or("/").to_owned();
                let response = handler(&path);
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.flush();
            }
        });
        format!("http://{address}")
    }

    fn ok_response(content_type: &str, body: &str) -> String {
        format!(
            "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
    }

    /// The desktop truncates the model-visible text at 30 000 chars and says so in
    /// the same words; a 20 000-char mobile cut delivered less than the desktop.
    #[tokio::test]
    async fn long_text_is_truncated_at_the_desktop_limit_with_the_desktop_marker() {
        let body = format!("{}TAIL-SENTINEL", "x".repeat(40_000));
        let body_len = body.chars().count();
        let base = serve(move |_| ok_response("text/plain", &body));
        let tools = WebFetchTools::new();
        let result = tools
            .execute(&ToolCall {
                id: "call".into(),
                name: "web_fetch".into(),
                arguments: json!({"url": base}),
            })
            .await
            .unwrap();
        let content = result["content"].as_str().unwrap();
        let marker = format!("\n\n[... truncated at 30000 / {body_len} chars]");
        assert!(
            content.ends_with(&marker),
            "unexpected tail: {}",
            &content[content.len().saturating_sub(80)..]
        );
        assert_eq!(content.chars().count(), 30_000 + marker.chars().count());
        assert_eq!(result["truncated"], json!(true));
        assert!(!content.contains("TAIL-SENTINEL"));
    }

    /// The desktop reads the whole body; the phone used to cut it at 512 KiB, so
    /// readable content past that point was lost even when the text itself fit.
    #[tokio::test]
    async fn a_large_body_is_read_past_the_old_byte_cap() {
        let body = format!(
            "<html><body><script>{}</script><p>TAIL-SENTINEL</p></body></html>",
            "x".repeat(600 * 1024)
        );
        let base = serve(move |_| ok_response("text/html", &body));
        let tools = WebFetchTools::new();
        let result = tools
            .execute(&ToolCall {
                id: "call".into(),
                name: "web_fetch".into(),
                arguments: json!({"url": base}),
            })
            .await
            .unwrap();
        let content = result["content"].as_str().unwrap();
        assert!(content.contains("TAIL-SENTINEL"), "content past 512 KiB was dropped");
        assert_eq!(result["truncated"], json!(false));
    }

    /// httpx follows up to 20 redirects; the phone stopped after five.
    #[tokio::test]
    async fn redirect_chain_follows_more_than_five_hops() {
        let base = serve(|path| {
            let hop = path.trim_start_matches('/');
            let next = hop.parse::<u32>().map(|value| value + 1).unwrap_or(1);
            if next <= 6 {
                format!("HTTP/1.1 302 Found\r\nLocation: /{next}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            } else {
                ok_response("text/plain", "ARRIVED")
            }
        });
        let tools = WebFetchTools::new();
        let result = tools
            .execute(&ToolCall {
                id: "call".into(),
                name: "web_fetch".into(),
                arguments: json!({"url": format!("{base}/0")}),
            })
            .await
            .unwrap();
        assert!(result["content"].as_str().unwrap().contains("ARRIVED"));
    }
}
