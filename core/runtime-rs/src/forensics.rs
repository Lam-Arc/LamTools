//! Opt-in raw HTTP entity bodies. No authentication headers or error text.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::Write,
    path::PathBuf,
};

tokio::task_local! { pub(crate) static CONTEXT: Value; }

pub(crate) fn identity(hook: &crate::hooks::HookRunContext, turn: &str, step: usize) -> Value {
    let session = &hook.session_id;
    let run = if hook.run_id.is_empty() {
        turn
    } else {
        &hook.run_id
    };
    json!({"session_id": session, "run_id": run, "turn_id": turn, "step": step,
           "identity_status": if session.is_empty() || run.is_empty() { "partial_or_unavailable" } else { "available" }})
}

pub(crate) fn client_builder(builder: reqwest::ClientBuilder) -> reqwest::ClientBuilder {
    if enabled() {
        // The caller records redirect hops explicitly, then follows them.
        // Decompression would hide raw entity bytes from the public stream.
        builder
            .redirect(reqwest::redirect::Policy::none())
            .no_gzip()
            .no_brotli()
            .no_deflate()
            .no_zstd()
    } else {
        builder
    }
}

pub(crate) fn enabled() -> bool {
    std::env::var("LAMTOOLS_LLM_RAW_RECORDING")
        .map(|v| {
            matches!(
                v.trim().to_ascii_lowercase().as_str(),
                "1" | "true" | "yes" | "on"
            )
        })
        .unwrap_or(false)
}

pub(crate) struct Capture {
    path: PathBuf,
    meta: Value,
    response_hash: Sha256,
}

impl Capture {
    pub(crate) fn start(
        request: &reqwest::Request,
        context: Value,
    ) -> Result<Option<Self>, String> {
        if !enabled() {
            return Ok(None);
        }
        let root = std::env::var("LAMTOOLS_LLM_FORENSIC_DIR").unwrap_or_else(|_| {
            format!(
                "{}/llm-forensics",
                std::env::var("LAMTOOLS_CORE_DATA_DIR").unwrap_or("data".into())
            )
        });
        Self::start_at(request, context, PathBuf::from(root)).map(Some)
    }

    pub(crate) fn start_at(
        request: &reqwest::Request,
        context: Value,
        root: PathBuf,
    ) -> Result<Self, String> {
        let mut url = request.url().clone();
        let _ = url.set_username("");
        let _ = url.set_password(None);
        url.set_query(None);
        url.set_fragment(None);
        let id = uuid::Uuid::new_v4().simple().to_string();
        let path = root.join(&id);
        fs::create_dir_all(&path).map_err(|_| "forensic directory creation failed")?;
        let mut meta = context;
        if let Ok(identity) = CONTEXT.try_with(Clone::clone) {
            if let Some(fields) = identity.as_object() {
                for (key, value) in fields {
                    meta[key] = value.clone();
                }
            }
        }
        meta["version"] = json!(1);
        meta["record_id"] = json!(id);
        meta["endpoint"] = json!(url.as_str());
        meta["started_at"] = json!(chrono::Utc::now().to_rfc3339());
        meta["capture_state"] = json!("in_progress");
        meta["request_complete"] = json!(false);
        meta["response_complete"] = json!(false);
        meta["request_sha256"] = json!(format!("{:x}", Sha256::digest([])));
        meta["response_sha256"] = json!(format!("{:x}", Sha256::digest([])));
        meta["request_bytes"] = json!(0);
        meta["response_bytes"] = json!(0);
        meta["status"] = Value::Null;
        meta["method"] = json!(request.method().as_str());
        let mut capture = Self {
            path,
            meta,
            response_hash: Sha256::new(),
        };
        capture.save()?;
        let body = match request.body() {
            None => &[][..],
            Some(body) => body
                .as_bytes()
                .ok_or("forensic request body is not serialized bytes")?,
        };
        let mut file = File::create(capture.path.join("request.bin"))
            .map_err(|_| "forensic request create failed")?;
        file.write_all(body)
            .and_then(|_| file.sync_all())
            .map_err(|_| "forensic request write failed")?;
        File::create(capture.path.join("response.bin"))
            .map_err(|_| "forensic response create failed")?;
        capture.meta["request_bytes"] = json!(body.len());
        capture.meta["request_sha256"] = json!(format!("{:x}", Sha256::digest(body)));
        capture.meta["request_complete"] = json!(true);
        capture.save()?;
        Ok(capture)
    }

    pub(crate) fn fail(&mut self, kind: &str) -> Result<(), String> {
        for side in ["request", "response"] {
            self.meta[format!("{side}_bytes")] =
                fs::metadata(self.path.join(format!("{side}.bin")))
                    .map(|m| json!(m.len()))
                    .unwrap_or(Value::Null);
        }
        self.meta["capture_state"] = json!("failed");
        self.meta["error_type"] = json!(kind);
        self.meta["ended_at"] = json!(chrono::Utc::now().to_rfc3339());
        self.save()
    }

    fn save(&self) -> Result<(), String> {
        let bytes = serde_json::to_vec_pretty(&self.meta)
            .map_err(|_| "forensic metadata encoding failed")?;
        // In-place manifests: body data is never replaced. A crash during a
        // manifest write yields invalid metadata, explicitly incomplete.
        let mut file = File::create(self.path.join("metadata.json"))
            .map_err(|_| "forensic metadata create failed")?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "forensic metadata write failed".into())
    }

    fn append(&mut self, bytes: &[u8]) -> Result<(), String> {
        let mut file = OpenOptions::new()
            .append(true)
            .open(self.path.join("response.bin"))
            .map_err(|_| "forensic response open failed")?;
        file.write_all(bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "forensic response write failed")?;
        self.response_hash.update(bytes);
        self.meta["response_bytes"] =
            json!(file.metadata().map_err(|_| "forensic stat failed")?.len());
        self.meta["response_sha256"] =
            json!(format!("{:x}", self.response_hash.clone().finalize()));
        self.save()
    }

    fn eof(&mut self) -> Result<(), String> {
        self.meta["capture_state"] = json!("complete");
        self.meta["response_complete"] = json!(true);
        self.meta["ended_at"] = json!(chrono::Utc::now().to_rfc3339());
        self.save()
    }
}

pub(crate) fn redirect_request(
    request: &reqwest::Request,
    response: &Response,
    index: usize,
) -> Result<Option<reqwest::Request>, String> {
    if !response.recording() || !matches!(response.status().as_u16(), 301 | 302 | 303 | 307 | 308) {
        return Ok(None);
    }
    let Some(location) = response
        .headers()
        .get(reqwest::header::LOCATION)
        .and_then(|v| v.to_str().ok())
    else {
        return Ok(None);
    };
    if index >= 10 {
        return Err("provider redirect limit exceeded".into());
    }
    let url = request
        .url()
        .join(location)
        .map_err(|_| "invalid provider redirect URL")?;
    let mut next = request
        .try_clone()
        .ok_or("provider redirect request cannot be cloned")?;
    if matches!(response.status().as_u16(), 301 | 302 | 303) {
        *next.body_mut() = None;
        for header in [
            reqwest::header::CONTENT_LENGTH,
            reqwest::header::CONTENT_TYPE,
            reqwest::header::TRANSFER_ENCODING,
            reqwest::header::CONTENT_ENCODING,
        ] {
            next.headers_mut().remove(header);
        }
        if next.method() != reqwest::Method::GET && next.method() != reqwest::Method::HEAD {
            *next.method_mut() = reqwest::Method::GET;
        }
    }
    if url.host_str() != request.url().host_str()
        || url.port_or_known_default() != request.url().port_or_known_default()
    {
        for header in [
            reqwest::header::AUTHORIZATION,
            reqwest::header::COOKIE,
            reqwest::header::PROXY_AUTHORIZATION,
        ] {
            next.headers_mut().remove(header);
        }
    }
    let mut referer = request.url().clone();
    let _ = referer.set_username("");
    let _ = referer.set_password(None);
    referer.set_fragment(None);
    if !(referer.scheme() == "https" && url.scheme() == "http") {
        if let Ok(value) = reqwest::header::HeaderValue::from_str(referer.as_str()) {
            next.headers_mut().insert(reqwest::header::REFERER, value);
        }
    } else {
        next.headers_mut().remove(reqwest::header::REFERER);
    }
    *next.url_mut() = url;
    Ok(Some(next))
}

impl Drop for Capture {
    fn drop(&mut self) {
        if self.meta["capture_state"] == "in_progress" {
            self.meta["capture_state"] = json!("interrupted");
            self.meta["ended_at"] = json!(chrono::Utc::now().to_rfc3339());
            if self.save().is_err() {
                eprintln!("Forensic capture persistence failed; record is incomplete");
            }
        }
    }
}

pub(crate) struct Response {
    inner: reqwest::Response,
    capture: Option<Capture>,
}

impl From<reqwest::Response> for Response {
    fn from(inner: reqwest::Response) -> Self {
        Self {
            inner,
            capture: None,
        }
    }
}

impl Response {
    pub(crate) fn new(
        inner: reqwest::Response,
        mut capture: Option<Capture>,
    ) -> Result<Self, String> {
        if let Some(c) = &mut capture {
            c.meta["status"] = json!(inner.status().as_u16());
            c.meta["http_state"] = json!(if inner.status().is_success() {
                "success"
            } else {
                "non_success"
            });
            c.meta["headers_received_at"] = json!(chrono::Utc::now().to_rfc3339());
            c.save()?;
        }
        Ok(Self { inner, capture })
    }
    pub(crate) fn recording(&self) -> bool {
        self.capture.is_some()
    }
    pub(crate) fn status(&self) -> reqwest::StatusCode {
        self.inner.status()
    }
    pub(crate) fn headers(&self) -> &reqwest::header::HeaderMap {
        self.inner.headers()
    }
    pub(crate) async fn chunk(&mut self) -> Result<Option<Vec<u8>>, String> {
        match self.inner.chunk().await {
            Ok(Some(bytes)) => {
                if let Some(c) = &mut self.capture {
                    if let Err(error) = c.append(&bytes) {
                        if c.fail("capture_storage_failed").is_err() {
                            eprintln!("Forensic failure metadata could not be persisted; record is incomplete");
                        }
                        return Err(error);
                    }
                }
                Ok(Some(bytes.to_vec()))
            }
            Ok(None) => {
                if let Some(c) = &mut self.capture {
                    c.eof()?;
                }
                Ok(None)
            }
            Err(_) => {
                if let Some(c) = &mut self.capture {
                    c.meta["capture_state"] = json!("failed");
                    c.meta["error_type"] = json!("transport_error");
                    c.save()?;
                }
                Err("provider body read failed".into())
            }
        }
    }
    pub(crate) async fn drain(&mut self, idle: Option<std::time::Duration>) -> Result<(), String> {
        if !self.recording() {
            return Ok(());
        }
        loop {
            let next = if let Some(timeout) = idle {
                tokio::time::timeout(timeout, self.chunk())
                    .await
                    .map_err(|_| "forensic stream idle timeout")??
            } else {
                self.chunk().await?
            };
            if next.is_none() {
                return Ok(());
            }
        }
    }
    pub(crate) async fn text(mut self) -> Result<String, String> {
        if self.capture.is_none() {
            return self.inner.text().await.map_err(|e| e.to_string());
        }
        let mut body = Vec::new();
        while let Some(chunk) = self.chunk().await? {
            body.extend(chunk);
        }
        Ok(String::from_utf8_lossy(&body).into_owned())
    }
    pub(crate) async fn json<T: serde::de::DeserializeOwned>(self) -> Result<T, String> {
        if self.capture.is_none() {
            return self.inner.json().await.map_err(|e| e.to_string());
        }
        serde_json::from_str(&self.text().await?).map_err(|e| e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;

    fn capture(request: &reqwest::Request) -> Capture {
        Capture::start_at(
            request,
            json!({"model":"mock", "retry_index": 2}),
            std::env::temp_dir().join(format!("quality-task-1-{}", uuid::Uuid::new_v4())),
        )
        .unwrap()
    }

    #[test]
    fn serialized_request_and_interrupted_manifest() {
        let request = reqwest::Client::new()
            .post("https://user:secret@example.test/api?key=secret")
            .bearer_auth("AUTH_SECRET")
            .body(vec![0, 255, 10, 13])
            .build()
            .unwrap();
        let c = capture(&request);
        let path = c.path.clone();
        assert_eq!(
            fs::read(path.join("request.bin")).unwrap(),
            vec![0, 255, 10, 13]
        );
        drop(c);
        let text = fs::read_to_string(path.join("metadata.json")).unwrap();
        let meta: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(meta["capture_state"], "interrupted");
        assert_eq!(meta["request_bytes"], 4);
        assert_eq!(meta["response_complete"], false);
        assert!(!text.contains("secret") && !text.contains("AUTH_SECRET"));
        fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }

    #[tokio::test]
    async fn raw_chunks_and_drain_after_done() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            let mut input = [0; 4096];
            socket.read(&mut input).unwrap();
            socket.write_all(b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Type: text/event-stream\r\n\r\ndata: [DONE]\n\n").unwrap();
            socket.flush().unwrap();
            std::thread::sleep(std::time::Duration::from_millis(40));
            socket.write_all(b"trailing\x00\xff").unwrap();
        });
        let client = reqwest::Client::new();
        let request = client
            .post(format!("http://{address}"))
            .body("exact body")
            .build()
            .unwrap();
        let c = capture(&request);
        let path = c.path.clone();
        let mut response = Response::new(client.execute(request).await.unwrap(), Some(c)).unwrap();
        let mut prefix = Vec::new();
        while !prefix.windows(6).any(|w| w == b"[DONE]") {
            prefix.extend(response.chunk().await.unwrap().unwrap());
        }
        response
            .drain(Some(std::time::Duration::from_secs(2)))
            .await
            .unwrap();
        drop(response);
        server.join().unwrap();
        assert_eq!(
            fs::read(path.join("response.bin")).unwrap(),
            b"data: [DONE]\n\ntrailing\x00\xff"
        );
        let meta: Value =
            serde_json::from_slice(&fs::read(path.join("metadata.json")).unwrap()).unwrap();
        assert_eq!(meta["capture_state"], "complete");
        assert_eq!(meta["response_bytes"], 24);
        fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }

    #[test]
    fn failed_capture_keeps_available_evidence() {
        let request = reqwest::Client::new()
            .post("https://example.test")
            .body("{}")
            .build()
            .unwrap();
        let mut c = capture(&request);
        let path = c.path.clone();
        c.append(b"partial evidence").unwrap();
        c.fail("transport_error").unwrap();
        drop(c);
        let meta: Value =
            serde_json::from_slice(&fs::read(path.join("metadata.json")).unwrap()).unwrap();
        assert_eq!(meta["capture_state"], "failed");
        assert_eq!(meta["response_complete"], false);
        assert_eq!(
            fs::read(path.join("response.bin")).unwrap(),
            b"partial evidence"
        );
        fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }

    #[tokio::test]
    async fn redirect_body_is_preserved_before_following() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let server = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket.read(&mut [0; 4096]).unwrap();
            socket.write_all(b"HTTP/1.1 307 Temporary Redirect\r\nLocation: /final\r\nContent-Length: 17\r\nConnection: close\r\n\r\nredirect evidence").unwrap();
        });
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .unwrap();
        let request = client
            .post(format!("http://{address}/first"))
            .bearer_auth("SECRET")
            .body(vec![0, 255, 10])
            .build()
            .unwrap();
        let original = request.try_clone().unwrap();
        let c = capture(&request);
        let path = c.path.clone();
        let mut response = Response::new(client.execute(request).await.unwrap(), Some(c)).unwrap();
        let next = redirect_request(&original, &response, 0).unwrap().unwrap();
        assert_eq!(next.method(), reqwest::Method::POST);
        assert_eq!(next.url().path(), "/final");
        assert_eq!(next.body().unwrap().as_bytes().unwrap(), &[0, 255, 10]);
        assert_eq!(
            next.headers()[reqwest::header::AUTHORIZATION],
            "Bearer SECRET"
        );
        response
            .drain(Some(std::time::Duration::from_secs(2)))
            .await
            .unwrap();
        drop(response);
        server.join().unwrap();
        assert_eq!(
            fs::read(path.join("response.bin")).unwrap(),
            b"redirect evidence"
        );
        let meta: Value =
            serde_json::from_slice(&fs::read(path.join("metadata.json")).unwrap()).unwrap();
        assert_eq!(meta["capture_state"], "complete");
        assert_eq!(meta["status"], 307);
        fs::remove_dir_all(path.parent().unwrap()).unwrap();
    }
}
