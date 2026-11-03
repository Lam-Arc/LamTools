//! `web_fetch`. Ported from the validated trial; the two pure functions are
//! carried over unchanged, which is the only part of the old module that
//! survived contact with the new contract.

use regex_lite::Regex;
use serde_json::{json, Value};
use std::time::Duration;
use sunday_protocol::{
    CoreError, HostKind, Permission, SideEffect, Tool, ToolCtx, ToolOutput, ToolSpec,
};
use url::Url;

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);
const MAX_TEXT_CHARS: usize = 30_000;
const MAX_REDIRECTS: usize = 20;

/// Collapse an HTML document to readable text.
fn html_to_text(body: &str) -> String {
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

/// Checks a URL before it becomes a request.
///
/// `first_hop` is false for every redirect: a server does not get to decide that the
/// client may now reach this machine.
fn guard_url(raw: &str, allow_local: bool) -> Result<Url, CoreError> {
    let parsed = Url::parse(raw)
        .map_err(|e| CoreError::invalid(format!("'url' must be an absolute URL: {e}")))?;
    if !matches!(parsed.scheme(), "http" | "https") {
        return Err(CoreError::invalid(format!(
            "scheme {:?} is refused: only http and https URLs can be fetched",
            parsed.scheme()
        )));
    }
    if !parsed.username().is_empty() || parsed.password().is_some() {
        return Err(CoreError::invalid(
            "credentials in a fetch URL are refused: they would be sent in clear text and logged",
        ));
    }
    let host = parsed
        .host_str()
        .ok_or_else(|| CoreError::invalid("the URL has no host"))?;
    if !allow_local && sunday_platform::is_local_host(host) {
        return Err(CoreError::PermissionDenied {
            resource: format!(
                "{host} is this machine or a private network; a fetch tool is not a way to read those"
            ),
        });
    }
    Ok(parsed)
}

pub struct WebFetch {
    timeout: Duration,
    /// Whether the *configured* target may be on this machine.
    ///
    /// Off by default. On, it lets a deliberately configured local server be fetched;
    /// it never lets a redirect go there, because that decision belongs to whichever
    /// server sent the redirect.
    allow_local: bool,
    spec: ToolSpec,
}

impl Default for WebFetch {
    fn default() -> Self {
        Self::new(DEFAULT_TIMEOUT)
    }
}

impl WebFetch {
    pub fn new(timeout: Duration) -> Self {
        Self::with_local_endpoints(timeout, false)
    }

    /// Only for a host that has decided to reach a local server, and for the tests
    /// that need one to talk to.
    pub fn allowing_local_endpoints(timeout: Duration) -> Self {
        Self::with_local_endpoints(timeout, true)
    }

    fn with_local_endpoints(timeout: Duration, allow_local: bool) -> Self {
        Self {
            timeout,
            allow_local,
            spec: ToolSpec {
                id: "web_fetch".into(),
                description: "Fetch one http(s) URL and return its readable text. HTML is reduced \
                              to text; the result is truncated."
                    .into(),
                input_schema: json!({
                    "type": "object",
                    "additionalProperties": false,
                    "properties": {"url": {"type": "string", "description": "Absolute http(s) URL"}},
                    "required": ["url"]
                }),
                side_effect: SideEffect::Pure,
                hosts: vec![HostKind::Windows, HostKind::Android, HostKind::Server],
                permission: Permission::AskUser,
            },
        }
    }
}

#[async_trait::async_trait]
impl Tool for WebFetch {
    fn spec(&self) -> &ToolSpec {
        &self.spec
    }

    async fn execute(&self, args: Value, _ctx: &ToolCtx) -> Result<ToolOutput, CoreError> {
        let raw = args
            .get("url")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_owned();
        let mut current = guard_url(&raw, self.allow_local)?;
        let client = reqwest::Client::builder()
            .timeout(self.timeout)
            .connect_timeout(Duration::from_secs(15))
            // Redirects are followed by hand so every hop passes `guard_url`. Asking
            // reqwest to follow them gives us no way to look at the target.
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| CoreError::model(format!("fetch client: {e}")))?;

        let mut response = None;
        for _ in 0..MAX_REDIRECTS {
            let reply = client.get(current.as_str()).send().await.map_err(|e| {
                if e.is_timeout() {
                    CoreError::model("fetch timed out")
                } else {
                    CoreError::model(format!("fetch failed: {e}"))
                }
            })?;
            if !reply.status().is_redirection() {
                response = Some(reply);
                break;
            }
            let location = reply
                .headers()
                .get(reqwest::header::LOCATION)
                .and_then(|value| value.to_str().ok())
                .ok_or_else(|| CoreError::model("a redirect with no location"))?;
            let next = current
                .join(location)
                .map_err(|e| CoreError::model(format!("bad redirect target: {e}")))?;
            // Always strict on a hop, whatever the configured target was allowed.
            current = guard_url(next.as_str(), false)?;
        }
        let response = response
            .ok_or_else(|| CoreError::model(format!("more than {MAX_REDIRECTS} redirects")))?;
        let url = current.to_string();
        let status = response.status();
        if !status.is_success() {
            return Err(CoreError::model(format!(
                "fetch failed: HTTP {}",
                status.as_u16()
            )));
        }
        let content_type = response
            .headers()
            .get("content-type")
            .and_then(|v| v.to_str().ok())
            .unwrap_or_default()
            .to_ascii_lowercase();
        let body = response
            .bytes()
            .await
            .map_err(|e| CoreError::model(format!("read failed: {e}")))?;
        let raw = String::from_utf8_lossy(&body).into_owned();
        let is_html = content_type.contains("html")
            || raw.trim_start().starts_with("<!DOCTYPE")
            || raw.trim_start().starts_with("<html");
        let text = if is_html { html_to_text(&raw) } else { raw };
        let total_chars = text.chars().count();
        let clipped = total_chars > MAX_TEXT_CHARS;
        let text = if clipped {
            format!(
                "{}\n\n[... truncated at {MAX_TEXT_CHARS} / {total_chars} chars]",
                text.chars().take(MAX_TEXT_CHARS).collect::<String>()
            )
        } else {
            text
        };
        Ok(ToolOutput {
            content: json!({
                "ok": true,
                "url": url,
                "content_type": content_type,
                "content": text,
                "truncated": clipped,
            })
            .to_string(),
            is_error: false,
        })
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
        assert!(!text.contains("var x=1"));
        assert!(!text.contains("p{}"));
        assert!(text.lines().any(|line| line == "Title"));
    }

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

    /// The same fixture server, but counting the connections it accepts.
    fn serve_counting<F>(hits: std::sync::Arc<std::sync::atomic::AtomicUsize>, handler: F) -> String
    where
        F: Fn(&str) -> String + Send + Sync + 'static,
    {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                hits.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
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

    #[test]
    fn the_spec_declares_the_expected_contract() {
        let tool = WebFetch::default();
        assert_eq!(tool.spec().id, "web_fetch");
        assert_eq!(tool.spec().permission, Permission::AskUser);
        assert_eq!(tool.spec().side_effect, SideEffect::Pure);
        assert!(tool.spec().available_on(HostKind::Android));
        assert_eq!(tool.spec().input_schema["required"], json!(["url"]));
    }

    #[tokio::test]
    async fn a_relative_url_is_rejected_before_any_request() {
        let tool = WebFetch::default();
        let err = tool
            .execute(json!({"url": "example.com/page"}), &ToolCtx::default())
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::InvalidRequest { .. }));
    }

    #[tokio::test]
    async fn html_is_reduced_and_json_is_passed_through() {
        let base = serve(|path| match path {
            "/page" => ok_response("text/html", "<html><body><p>hello</p></body></html>"),
            _ => ok_response("application/json", "{\"a\":1}"),
        });
        // Explicit: this is a fetch to this machine, which is refused by default.
        let tool = WebFetch::allowing_local_endpoints(DEFAULT_TIMEOUT);

        let html = tool
            .execute(json!({"url": format!("{base}/page")}), &ToolCtx::default())
            .await
            .unwrap();
        let parsed: Value = serde_json::from_str(&html.content).unwrap();
        assert_eq!(parsed["content"], "hello");

        let json_body = tool
            .execute(json!({"url": format!("{base}/data")}), &ToolCtx::default())
            .await
            .unwrap();
        let parsed: Value = serde_json::from_str(&json_body.content).unwrap();
        assert_eq!(parsed["content"], "{\"a\":1}");
    }

    #[tokio::test]
    async fn an_http_error_is_reported_not_swallowed() {
        let base = serve(|_| {
            "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".to_string()
        });
        let tool = WebFetch::allowing_local_endpoints(DEFAULT_TIMEOUT);
        let err = tool
            .execute(
                json!({"url": format!("{base}/missing")}),
                &ToolCtx::default(),
            )
            .await
            .unwrap_err();
        match err {
            CoreError::Model { reason } => assert!(reason.contains("404")),
            other => panic!("expected a model error with the status, got {other:?}"),
        }
    }

    #[tokio::test]
    async fn a_missing_url_argument_is_an_invalid_request_not_a_panic() {
        let tool = WebFetch::default();
        let err = tool
            .execute(json!({}), &ToolCtx::default())
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::InvalidRequest { .. }));
    }

    /// The default must refuse this machine. A `Pure` tool pointed at `127.0.0.1` is
    /// a way to read whatever local service happens to be listening.
    #[tokio::test]
    async fn this_machine_is_refused_by_default() {
        let base = serve(|_| ok_response("text/plain", "local secret"));
        let tool = WebFetch::default();
        let err = tool
            .execute(
                json!({"url": format!("{base}/secret")}),
                &ToolCtx::default(),
            )
            .await
            .unwrap_err();
        assert!(
            matches!(err, CoreError::PermissionDenied { .. }),
            "a fetch to loopback was not refused: {err:?}"
        );
        assert!(
            !format!("{err:?}").contains("local secret"),
            "the refusal leaked the body it refused to read"
        );
    }

    /// A cloud metadata endpoint hands out credentials to anything that asks.
    #[tokio::test]
    async fn a_metadata_endpoint_is_refused_by_default() {
        let tool = WebFetch::default();
        for url in [
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://[fd00:ec2::254]/latest/meta-data/",
            "http://10.0.0.5/admin",
        ] {
            let err = tool
                .execute(json!({"url": url}), &ToolCtx::default())
                .await
                .unwrap_err();
            assert!(
                matches!(err, CoreError::PermissionDenied { .. }),
                "{url} was not refused: {err:?}"
            );
        }
    }

    /// `file://` was already refused by the prefix check; it must stay refused now
    /// that the URL is parsed properly.
    #[tokio::test]
    async fn a_non_http_scheme_is_refused() {
        let tool = WebFetch::default();
        for url in [
            "file:///etc/passwd",
            "ftp://example.com/x",
            "data:text/plain,hello",
        ] {
            let err = tool
                .execute(json!({"url": url}), &ToolCtx::default())
                .await
                .unwrap_err();
            assert!(
                matches!(err, CoreError::InvalidRequest { .. }),
                "{url} was not refused as a scheme problem: {err:?}"
            );
        }
    }

    /// Credentials in a fetch URL would be sent in clear text and land in every log.
    #[tokio::test]
    async fn credentials_in_the_url_are_refused() {
        let tool = WebFetch::default();
        let err = tool
            .execute(
                json!({"url": "https://user:token@example.com/x"}),
                &ToolCtx::default(),
            )
            .await
            .unwrap_err();
        assert!(matches!(err, CoreError::InvalidRequest { .. }), "{err:?}");
    }

    /// The redirect case: the first hop is a local server that the caller allowed,
    /// and it answers `302` to a *different* local server. The second server must
    /// receive nothing, because a redirect does not carry the permission with it.
    #[tokio::test]
    async fn a_redirect_to_this_machine_is_not_followed() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::Arc;

        let hits = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&hits);
        // The target: a second local server that counts what reaches it.
        let target = serve_counting(counter, |_| ok_response("text/plain", "secret"));
        let location = format!("{target}/latest/meta-data/");
        let gateway = serve(move |_| {
            format!(
                "HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
        });

        let tool = WebFetch::allowing_local_endpoints(DEFAULT_TIMEOUT);
        let err = tool
            .execute(
                json!({"url": format!("{gateway}/start")}),
                &ToolCtx::default(),
            )
            .await
            .unwrap_err();
        assert!(
            matches!(err, CoreError::PermissionDenied { .. }),
            "a redirect to this machine was followed: {err:?}"
        );
        assert_eq!(
            hits.load(Ordering::SeqCst),
            0,
            "the redirect target was contacted, so the hop was not checked before the request"
        );
    }
}
