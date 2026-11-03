//! Parity tests for tool behaviour that already existed in the Python core.

use sunday_protocol::{CoreError, Tool, ToolCtx};

/// Python keeps the model-visible text at 30 000 characters and appends
/// `[... N characters truncated ...]`; the Rust host was written to use the same
/// limit and its own marker (`core/runtime-rs/src/fetch_tools.rs:16`, itself
/// copied from `tool/web_tools.py`'s `clean[:30000]`).
///
/// The marker wording changed between the two Rust generations, so this test pins
/// the sentence rather than pretending it matches Python byte for byte.
#[tokio::test]
async fn the_truncation_marker_is_the_documented_one() {
    fn serve(body: String) -> String {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                let mut buffer = [0u8; 4096];
                let _ = stream.read(&mut buffer);
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.flush();
            }
        });
        format!("http://{address}")
    }

    let body = format!("{}TAIL", "x".repeat(40_000));
    let length = body.chars().count();
    let base = serve(body);
    let tool = sunday_tools::web_fetch::WebFetch::default();
    let out = tool
        .execute(serde_json::json!({"url": base}), &ToolCtx::default())
        .await
        .unwrap();
    let parsed: serde_json::Value = serde_json::from_str(&out.content).unwrap();
    let content = parsed["content"].as_str().unwrap();
    assert!(content.ends_with(&format!("\n\n[... truncated at 30000 / {length} chars]")));
    assert!(
        !content.contains("TAIL"),
        "the tail must not survive truncation"
    );
}

/// Python strips `script`, `style` and `noscript` containers before removing tags
/// (`core/runtime-rs/src/fetch_tools.rs:47 html_to_text`, ported from the Python
/// web tools). The same page must reduce the same way.
#[test]
fn script_and_style_bodies_never_reach_the_model() {
    // The function is private, so the assertion goes through the public tool on a
    // page served locally.
    fn serve(body: &'static str) -> String {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut stream) = stream else { break };
                let mut buffer = [0u8; 4096];
                let _ = stream.read(&mut buffer);
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes());
                let _ = stream.flush();
            }
        });
        format!("http://{address}")
    }

    let page = "<html><head><style>p{color:red}</style><script>var secret=1</script></head>\
                <body><h1>Title</h1><p>Body &amp; more</p></body></html>";
    let base = serve(page);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    let out = runtime.block_on(async {
        sunday_tools::web_fetch::WebFetch::default()
            .execute(serde_json::json!({"url": base}), &ToolCtx::default())
            .await
            .unwrap()
    });
    let parsed: serde_json::Value = serde_json::from_str(&out.content).unwrap();
    let text = parsed["content"].as_str().unwrap();
    assert!(text.contains("Title"));
    assert!(text.contains("Body & more"));
    assert!(!text.contains("var secret"), "script body leaked: {text}");
    assert!(!text.contains("color:red"), "style body leaked: {text}");
}

/// A non-absolute URL is refused before any network call, matching the Python
/// tool's argument validation.
#[tokio::test]
async fn a_relative_url_is_refused_before_any_request() {
    let err = sunday_tools::web_fetch::WebFetch::default()
        .execute(
            serde_json::json!({"url": "example.com/x"}),
            &ToolCtx::default(),
        )
        .await
        .unwrap_err();
    assert!(
        matches!(err, CoreError::InvalidRequest { .. }),
        "got {err:?}"
    );
}
