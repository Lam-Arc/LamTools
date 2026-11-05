//! The HTTP surface the desktop UI expects, answered by the in-app core.
//!
//! The UI is shared with desktop, where projects and files come from an HTTP core. The
//! Android host runs the Rust core in-process, so this command is the adapter: the IPC
//! transport turns `kind: 'http'` requests into a call here, and `projects_http` decides
//! what they mean.
//!
//! The body is returned as text unless the reply is binary, which is what the raw file
//! endpoint needs. Keeping that distinction explicit beats base64-encoding every JSON
//! response for the sake of one endpoint.

use std::sync::Arc;

use tauri::State;

use crate::CoreState;

#[derive(serde::Serialize)]
pub struct HttpResponse {
    pub status: u16,
    pub content_type: String,
    /// Present when the reply is textual.
    pub body: Option<String>,
    /// Present when the reply is bytes, so the caller can build a Uint8Array.
    pub body_base64: Option<String>,
}

fn base64(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity((bytes.len() + 2) / 3 * 4);
    for chunk in bytes.chunks(3) {
        let first = chunk[0] as u32;
        let second = *chunk.get(1).unwrap_or(&0) as u32;
        let third = *chunk.get(2).unwrap_or(&0) as u32;
        let combined = (first << 16) | (second << 8) | third;
        out.push(ALPHABET[(combined >> 18) as usize & 63] as char);
        out.push(ALPHABET[(combined >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 {
            ALPHABET[(combined >> 6) as usize & 63] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            ALPHABET[combined as usize & 63] as char
        } else {
            '='
        });
    }
    out
}

/// Splits `path` into the part the router matches and the query it reads.
fn split_path(path: &str) -> (&str, &str) {
    match path.split_once('?') {
        Some((path, query)) => (path, query),
        None => (path, ""),
    }
}

fn serve(state: &CoreState, method: &str, raw_path: &str, body: &str) -> HttpResponse {
    let (path, query) = split_path(raw_path);
    let reply = state.projects.handle(method, path, query, body);
    // A binary reply is the raw file endpoint; everything else is JSON or empty.
    if reply.content_type == "application/octet-stream" {
        HttpResponse {
            status: reply.status,
            content_type: reply.content_type.to_owned(),
            body: None,
            body_base64: Some(base64(&reply.body)),
        }
    } else {
        HttpResponse {
            status: reply.status,
            content_type: reply.content_type.to_owned(),
            body: Some(String::from_utf8_lossy(&reply.body).into_owned()),
            body_base64: None,
        }
    }
}

#[tauri::command]
pub fn core_http(
    state: State<'_, Arc<CoreState>>,
    method: String,
    path: String,
    body: Option<String>,
) -> HttpResponse {
    let reply = serve(&state, &method, &path, body.as_deref().unwrap_or(""));
    // One line per request, with the response size. Without it a screen that quietly
    // shows nothing is indistinguishable from one whose request never arrived, and from
    // one whose request returned an empty body.
    let size = reply
        .body
        .as_ref()
        .map(|text| text.len())
        .or_else(|| reply.body_base64.as_ref().map(|text| text.len()))
        .unwrap_or(0);
    println!(
        "core_http {} {} -> {} ({size} bytes)",
        method, path, reply.status
    );
    // The session list decides whether the app looks alive, so its payload is worth
    // seeing when it is suspected.
    if path.starts_with("/sessions") {
        if let Some(text) = reply.body.as_deref() {
            let preview: String = text.chars().take(240).collect();
            println!("core_http body: {preview}");
        }
    }
    reply
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base64_matches_the_reference_for_every_tail_length() {
        // Three tails: no padding, one pad, two pads. A wrong tail is invisible until an
        // image fails to render.
        assert_eq!(base64(b""), "");
        assert_eq!(base64(b"f"), "Zg==");
        assert_eq!(base64(b"fo"), "Zm8=");
        assert_eq!(base64(b"foo"), "Zm9v");
        assert_eq!(base64(b"foob"), "Zm9vYg==");
        assert_eq!(base64(b"fooba"), "Zm9vYmE=");
        assert_eq!(base64(b"foobar"), "Zm9vYmFy");
    }

    #[test]
    fn the_query_is_split_off_the_path() {
        assert_eq!(
            split_path("/projects/abc/files"),
            ("/projects/abc/files", "")
        );
        assert_eq!(
            split_path("/projects/abc/files?path=a.txt"),
            ("/projects/abc/files", "path=a.txt")
        );
    }
}
