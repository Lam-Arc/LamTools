//! Host-side update plumbing: read the release manifest, fetch the artifact.
//!
//! The app's WebView origin is `https://tauri.localhost`, which is cross-origin
//! to the release site. A `fetch` from the app therefore depends on the site
//! sending `Access-Control-Allow-Origin`; when it does not, the browser discards
//! an otherwise fine 200 and `fetch` rejects with `TypeError: Failed to fetch`,
//! which names neither the status nor the cause. On 2026-09-25 exactly that left
//! every installed build unable to check for updates until the Caddyfile was
//! patched.
//!
//! Fetching here removes the dependency: the host talks HTTP directly, reports
//! the real status, and the site's response headers stay a site concern. The
//! download below is the second half — a release artifact is only handed to an
//! installer after its bytes match the digest the manifest published.
use crate::RuntimeError;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio::io::AsyncWriteExt;

const TIMEOUT: Duration = Duration::from_secs(15);
const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
/// A release pointer is a few hundred bytes; anything larger is not it.
const MAX_MANIFEST_BYTES: usize = 64 * 1024;
const MAX_REDIRECTS: usize = 5;
/// Installers are tens of megabytes. This is a sanity bound against a wrong
/// URL, not a budget anyone should reach.
const MAX_ARTIFACT_BYTES: u64 = 512 * 1024 * 1024;
/// A 60 MB APK over a slow mobile link needs minutes, not seconds.
const DOWNLOAD_IDLE_TIMEOUT: Duration = Duration::from_secs(120);

/// One fetched release artifact.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DownloadedUpdate {
    pub bytes: u64,
    pub sha256: String,
}

/// Progress reports are advisory: the caller decides whether anyone listens.
pub type UpdateProgress<'a> = &'a (dyn Fn(u64, Option<u64>) + Send + Sync);

fn https_url(url: &str, what: &str) -> Result<reqwest::Url, RuntimeError> {
    let target = reqwest::Url::parse(url)
        .map_err(|error| RuntimeError::Tool(format!("{what} url is invalid: {error}")))?;
    // The URLs come from the app's own shell or from the manifest it just read.
    // https is required so a wrong value cannot turn into a cleartext fetch;
    // loopback http is allowed for the local test servers, where there is no
    // network to protect.
    let loopback = target
        .host_str()
        .is_some_and(|host| matches!(host, "localhost" | "127.0.0.1" | "[::1]" | "::1"));
    if target.scheme() != "https" && !(target.scheme() == "http" && loopback) {
        return Err(RuntimeError::Tool(format!("{what} must be fetched over https")));
    }
    Ok(target)
}

fn client(timeout: Duration) -> Result<reqwest::Client, RuntimeError> {
    reqwest::Client::builder()
        .timeout(timeout)
        .connect_timeout(CONNECT_TIMEOUT)
        .redirect(reqwest::redirect::Policy::limited(MAX_REDIRECTS))
        .build()
        .map_err(|error| RuntimeError::Tool(error.to_string()))
}

pub async fn fetch_update_manifest(url: &str) -> Result<Value, RuntimeError> {
    let target = https_url(url, "update manifest")?;
    let response = client(TIMEOUT)?
        .get(target)
        .header("Accept", "application/json")
        .send()
        .await
        .map_err(|error| {
            if error.is_timeout() {
                RuntimeError::Tool("update manifest request timed out".into())
            } else {
                RuntimeError::Tool(format!("update manifest request failed: {error}"))
            }
        })?;
    let status = response.status();
    if !status.is_success() {
        return Err(RuntimeError::Tool(format!(
            "update manifest HTTP {}",
            status.as_u16()
        )));
    }
    if response
        .content_length()
        .is_some_and(|length| length > MAX_MANIFEST_BYTES as u64)
    {
        return Err(RuntimeError::Tool(
            "update manifest is larger than expected".into(),
        ));
    }
    let body = response
        .bytes()
        .await
        .map_err(|error| RuntimeError::Tool(format!("update manifest body failed: {error}")))?;
    if body.len() > MAX_MANIFEST_BYTES {
        return Err(RuntimeError::Tool(
            "update manifest is larger than expected".into(),
        ));
    }
    serde_json::from_slice(&body)
        .map_err(|error| RuntimeError::Tool(format!("update manifest is not JSON: {error}")))
}

/// Download one release artifact and verify it against `expected_sha256`.
///
/// The bytes land in `<destination>.part` and are renamed only after the digest
/// matches, so an interrupted or tampered download can never be handed to an
/// installer — the file that an installer is pointed at is always the one the
/// manifest described. A mismatch removes the partial file and fails.
pub async fn download_update(
    url: &str,
    destination: &Path,
    expected_sha256: &str,
    progress: Option<UpdateProgress<'_>>,
) -> Result<DownloadedUpdate, RuntimeError> {
    let expected = expected_sha256.trim().to_ascii_lowercase();
    if expected.len() != 64 || !expected.chars().all(|character| character.is_ascii_hexdigit()) {
        return Err(RuntimeError::Tool(
            "the update manifest carries no usable sha256".into(),
        ));
    }
    let target = https_url(url, "update download")?;
    if let Some(parent) = destination.parent() {
        tokio::fs::create_dir_all(parent)
            .await
            .map_err(|error| RuntimeError::Tool(error.to_string()))?;
    }
    let partial = partial_path(destination);
    let response = client(DOWNLOAD_IDLE_TIMEOUT)?
        .get(target)
        .header("Accept", "application/octet-stream")
        .send()
        .await
        .map_err(|error| {
            if error.is_timeout() {
                RuntimeError::Tool("update download timed out".into())
            } else {
                RuntimeError::Tool(format!("update download failed: {error}"))
            }
        })?;
    let status = response.status();
    if !status.is_success() {
        return Err(RuntimeError::Tool(format!(
            "update download HTTP {}",
            status.as_u16()
        )));
    }
    let total = response.content_length();
    if total.is_some_and(|length| length > MAX_ARTIFACT_BYTES) {
        return Err(RuntimeError::Tool(
            "update download is larger than expected".into(),
        ));
    }

    let outcome = stream_to_file(response, &partial, total, progress).await;
    let (bytes, digest) = match outcome {
        Ok(value) => value,
        Err(error) => {
            let _ = tokio::fs::remove_file(&partial).await;
            return Err(error);
        }
    };
    if digest != expected {
        let _ = tokio::fs::remove_file(&partial).await;
        return Err(RuntimeError::Tool(format!(
            "downloaded update does not match the manifest sha256 (got {digest})"
        )));
    }
    tokio::fs::rename(&partial, destination)
        .await
        .map_err(|error| RuntimeError::Tool(error.to_string()))?;
    Ok(DownloadedUpdate {
        bytes,
        sha256: digest,
    })
}

async fn stream_to_file(
    mut response: reqwest::Response,
    partial: &Path,
    total: Option<u64>,
    progress: Option<UpdateProgress<'_>>,
) -> Result<(u64, String), RuntimeError> {
    let mut file = tokio::fs::File::create(partial)
        .await
        .map_err(|error| RuntimeError::Tool(error.to_string()))?;
    let mut hasher = Sha256::new();
    let mut received: u64 = 0;
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|error| RuntimeError::Tool(format!("update download failed: {error}")))?
    {
        received += chunk.len() as u64;
        if received > MAX_ARTIFACT_BYTES {
            return Err(RuntimeError::Tool(
                "update download is larger than expected".into(),
            ));
        }
        hasher.update(&chunk);
        file.write_all(&chunk)
            .await
            .map_err(|error| RuntimeError::Tool(error.to_string()))?;
        if let Some(report) = progress {
            report(received, total);
        }
    }
    file.flush()
        .await
        .map_err(|error| RuntimeError::Tool(error.to_string()))?;
    file.sync_all()
        .await
        .map_err(|error| RuntimeError::Tool(error.to_string()))?;
    drop(file);
    Ok((received, hex_digest(hasher.finalize().as_slice())))
}

/// `Sunday.setup.exe` → `Sunday.setup.exe.part` (kept beside the target so the
/// rename that publishes it is on the same filesystem).
fn partial_path(destination: &Path) -> PathBuf {
    let mut name = destination.as_os_str().to_owned();
    name.push(".part");
    PathBuf::from(name)
}

fn hex_digest(bytes: &[u8]) -> String {
    bytes
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::AsyncReadExt;
    use tokio::net::TcpListener;

    /// Serve one response, then keep the socket open long enough for the client
    /// to read it; the returned URL is http on loopback, which `https_url`
    /// deliberately allows for exactly this.
    async fn serve_once(body: Vec<u8>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind");
        let address = listener.local_addr().expect("addr");
        tokio::spawn(async move {
            if let Ok((mut socket, _)) = listener.accept().await {
                let mut buffer = [0u8; 2048];
                let _ = socket.read(&mut buffer).await;
                let header = format!(
                    "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                    body.len()
                );
                let _ = socket.write_all(header.as_bytes()).await;
                let _ = socket.write_all(&body).await;
                let _ = socket.flush().await;
            }
        });
        format!("http://{address}/artifact")
    }

    fn temporary_directory(name: &str) -> PathBuf {
        let path = std::env::temp_dir().join(format!("sunday-update-test-{name}"));
        let _ = std::fs::remove_dir_all(&path);
        path
    }

    #[tokio::test]
    async fn rejects_a_non_https_url() {
        let error = fetch_update_manifest("http://example.invalid/manifest.json")
            .await
            .expect_err("cleartext must be refused");
        assert!(error.to_string().contains("https"), "{error}");
    }

    #[tokio::test]
    async fn rejects_an_unparseable_url() {
        assert!(fetch_update_manifest("not a url").await.is_err());
    }

    #[tokio::test]
    async fn downloads_a_verified_artifact_and_reports_progress() {
        let body = b"installer bytes".to_vec();
        let digest = hex_digest(Sha256::digest(&body).as_slice());
        let url = serve_once(body.clone()).await;
        let directory = temporary_directory("verified");
        let destination = directory.join("Sunday.setup.exe");
        let seen = std::sync::Mutex::new(Vec::new());
        let progress = |received: u64, total: Option<u64>| {
            seen.lock().expect("lock").push((received, total));
        };

        let outcome = download_update(&url, &destination, &digest, Some(&progress))
            .await
            .expect("download");

        assert_eq!(outcome.bytes, body.len() as u64);
        assert_eq!(outcome.sha256, digest);
        assert_eq!(std::fs::read(&destination).expect("read back"), body);
        // The published file is the verified one; the partial never survives.
        assert!(!partial_path(&destination).exists());
        assert_eq!(seen.lock().expect("lock").len(), 1);
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[tokio::test]
    async fn a_tampered_artifact_is_refused_and_removed() {
        let url = serve_once(b"tampered bytes".to_vec()).await;
        let directory = temporary_directory("tampered");
        let destination = directory.join("Sunday.setup.exe");
        let expected = hex_digest(Sha256::digest(b"the real installer").as_slice());

        let error = download_update(&url, &destination, &expected, None)
            .await
            .expect_err("a digest mismatch must fail");

        assert!(error.to_string().contains("does not match"), "{error}");
        assert!(!destination.exists(), "the artifact must not be published");
        assert!(!partial_path(&destination).exists(), "the partial must go too");
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[tokio::test]
    async fn a_manifest_without_a_usable_hash_is_refused() {
        let destination = temporary_directory("no-hash").join("Sunday.setup.exe");
        for broken in ["", "abc", "zzzz"] {
            let error = download_update("https://example.invalid/x", &destination, broken, None)
                .await
                .expect_err("a missing digest must fail before any request");
            assert!(error.to_string().contains("sha256"), "{error}");
        }
    }
}
